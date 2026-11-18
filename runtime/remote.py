"""Non-blocking Textual adapter with client-local conversation subscriptions."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
import ipaddress
import json
import os
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from runtime.events import EventHistoryExpired, RuntimeEvent, RuntimeSnapshot
from runtime.wire import API_VERSION, PendingView, decode_snapshot, display_state


def validate_server_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in {"", "/"}):
        raise ValueError("Use an http(s) server origin without credentials, path, query or fragment")
    try:
        loopback = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        loopback = parts.hostname == "localhost"
    if parts.scheme == "http" and not loopback:
        raise ValueError("Remote servers require HTTPS; use Tailscale Serve")
    return url.rstrip("/")


class RemoteRuntimeClient:
    """Transport runs on its own thread. Every command captures its target chat.

    Switching subscriptions does not cancel HTTP requests or background runs.
    Lost replies may be retried with the SAME ID, never against a new epoch.
    """

    supports_privileged_approval = False

    def __init__(self, url: str, token: str):
        self.url = validate_server_url(url)
        if len(token) < 32 or not token.isascii() or token.strip() != token:
            raise ValueError("Set AI_AGENT_TOKEN to the server's token (at least 32 ASCII characters)")
        self._token = token
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._clients: set[str] = set()
        self._jobs: Queue[dict[str, Any]] = Queue(maxsize=64)
        self._read_jobs: Queue[dict[str, Any]] = Queue(maxsize=64)
        self._reads: set[str] = set()
        self._read_times: dict[str, float] = {}
        self._events: deque[RuntimeEvent] = deque(maxlen=2048)
        self._notices: deque[tuple[str, str]] = deque(maxlen=32)
        self._sequence = 0
        self._server_cursor = 0
        self._server_id: str | None = None
        self._connected = False
        self._state = display_state()
        self._snapshot = RuntimeSnapshot(0, (), None, "", False)
        self._pending: dict[int, PendingView] = {}
        self._providers: dict[str, Any] = {}
        self._models: dict[str, list[str]] = {}
        self._sessions: list[Any] = []
        self._turns: dict[str, list[dict[str, Any]]] = {}
        self.supports_multi_chat = False
        self._selected_session_id: str | None = None
        self._selection_generation = 0
        self._selection_ready = True
        self._navigation_request: str | None = None
        self._activity: dict[str, dict[str, Any]] = {}
        self._seen: dict[str, int] = {}
        self._chat_notices: dict[str, deque[tuple[str, str]]] = {}
        self._notice_unread: set[str] = set()

    @classmethod
    def from_environment(cls) -> RemoteRuntimeClient:
        return cls(os.environ.get("AI_AGENT_SERVER", "http://127.0.0.1:8765"),
                   os.environ.get("AI_AGENT_TOKEN", ""))

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def providers(self):
        with self._lock:
            return dict(self._providers)

    @property
    def connection_status(self) -> str:
        with self._lock:
            return "connected" if self._connected else "disconnected — reconnecting"

    def attach_client(self, *, can_approve: bool = False) -> str:
        if can_approve:
            raise PermissionError("Network clients cannot authorize privileged operations")
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("Create a new remote adapter after closing it")
            identity = uuid4().hex
            self._clients.add(identity)
            if self._thread is None:
                self._thread = Thread(target=self._thread_main, name="agent-api-client", daemon=True)
                self._thread.start()
            return identity

    def initialize(self) -> None:
        pass

    def detach_client(self, identity: str) -> None:
        with self._lock:
            self._clients.discard(identity)
            if self._clients:
                return
            self._stop.set()
            loop, task = self._loop, self._task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return replace(self._snapshot, sequence=self._sequence,
                           messages=self._snapshot.messages + tuple(self._notices))

    def events_since(self, sequence: int) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            if sequence < 0 or sequence > self._sequence:
                raise ValueError("Invalid client event cursor")
            if self._events and sequence < self._events[0].sequence - 1:
                raise EventHistoryExpired("Fetch a client snapshot")
            return tuple(e for e in self._events if e.sequence > sequence)

    def pending(self) -> dict[int, PendingView]:
        with self._lock:
            return dict(self._pending)

    def submit(self, text: str) -> None:
        self._command("submit", text=text)

    def new_chat(self, title: str = "") -> None:
        self._command("new_chat", title=title)

    def reset_context(self) -> None:
        self._command("reset_context")

    def reload_context(self) -> None:
        self._command("reload_context")

    def compact_context(self) -> None:
        self._command("compact_context")

    def load_chat(self, session_id: str) -> None:
        if self.supports_multi_chat:
            self._select_chat(session_id)
        else:
            self._command("load_chat", session_id=session_id)

    def session_activity(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            activity = dict(self._activity.get(session_id, {}))
            activity["unread"] = (activity.get("sequence", 0) > self._seen.get(session_id, 0)
                                  or session_id in self._notice_unread)
            return activity

    def _select_chat(self, session_id: str) -> None:
        if (not isinstance(session_id, str) or len(session_id) != 32
                or any(c not in "0123456789abcdef" for c in session_id)):
            raise ValueError("Invalid chat ID")
        with self._lock:
            if not self._connected:
                raise RuntimeError("Server disconnected; reconnect before switching chats")
            # Even reselecting the current chat supersedes a queued navigation.
            self._navigation_request = None
            if session_id == self._selected_session_id:
                return
            self._selected_session_id = session_id
            self._selection_generation += 1
            self._selection_ready = False
            self._navigation_request = None
            self._server_cursor = 0
            self._snapshot = RuntimeSnapshot(0, (), None, "", False)
            self._pending = {}
            self._state = display_state()
            self._state.chat_session_id = session_id
            self._state.cwd = "Switching chat…"
            self._notices = self._chat_notices.setdefault(session_id, deque(maxlen=32))
            self._emit("conversation_changed", messages=tuple(self._notices))
            self._emit("state_changed")

    def change_directory(self, path: str) -> None:
        self._command("change_directory", path=path)

    def switch_model(self, provider_key: str, model: str) -> None:
        self._command("switch_model", provider_key=provider_key, model=model)

    def set_model_setting(self, key: str, value: Any, *, client_id: str | None = None) -> None:
        if key == "elevated_commands":
            raise PermissionError("Privileged operations remain local-only")
        self._command("set_model_setting", key=key, value=value)

    def decide_pending(self, identity: int | str, *, accept: bool,
                       client_id: str | None = None, revision: str | None = None) -> None:
        if type(identity) is not int or revision is None or ":" not in revision:
            raise PermissionError("A reviewed file proposal and revision are required")
        parts = revision.split(":")
        with self._lock:
            if parts[0] != self._server_id:
                raise RuntimeError("Server changed; review the proposal again before deciding")
            if self.supports_multi_chat:
                if len(parts) != 3 or parts[1] != self._selected_session_id:
                    raise RuntimeError("Chat changed; review the proposal in its own chat before deciding")
            elif len(parts) != 2:
                raise RuntimeError("Invalid proposal review token")
            self._command("decide_pending", identity=identity, accept=accept, revision=parts[-1])

    def list_sessions(self, limit: int = 200):
        self._read("/v1/sessions")
        with self._lock:
            return self._sessions[:limit]

    def load_original_turns(self, session_id: str, limit: int = 32):
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            return []
        self._read(f"/v1/sessions/{session_id}/turns")
        with self._lock:
            return self._turns.get(session_id, [])[-limit:]

    def format_session_list(self, limit: int = 20) -> str:
        sessions = self.list_sessions(limit)
        if not sessions:
            return "History is loading, or no chat history exists. Open Chats to refresh."
        return "Recent chat sessions:\n" + "\n".join(
            f"{s.session_id[:12]} | turns={s.turn_count} | {s.provider_label} / {s.model}"
            for s in sessions
        )

    def provider_models(self, key: str) -> list[str]:
        if key not in self.providers:
            return []
        self._read(f"/v1/providers/{key}/models")
        with self._lock:
            return list(self._models.get(key, []))

    def _command(self, operation: str, **arguments: Any) -> None:
        with self._lock:
            if not self._connected or self._server_id is None or self._stop.is_set():
                raise RuntimeError("Server disconnected; commands are not queued offline")
            if self.supports_multi_chat and not self._selection_ready:
                raise RuntimeError("Chat is still loading; wait before sending commands")
            body: dict[str, Any] = {"operation": operation, "arguments": arguments,
                                    "request_id": uuid4().hex, "server_id": self._server_id}
            if self.supports_multi_chat:
                body["session_id"] = self._selected_session_id
            try:
                self._jobs.put_nowait({"kind": "command", "body": body})
                if operation == "new_chat":
                    self._navigation_request = body["request_id"]
            except Full:
                raise RuntimeError("Client command queue is full") from None

    def _read(self, path: str, *, force: bool = False) -> None:
        with self._lock:
            if (not self._connected or path in self._reads
                    or (not force and monotonic() - self._read_times.get(path, 0) < 2)):
                return
            try:
                self._read_jobs.put_nowait({"kind": "read", "path": path})
            except Full:
                return
            self._reads.add(path)

    def _emit(self, kind: str, text: str = "", *, role: str = "", messages=()) -> None:
        self._sequence += 1
        self._events.append(RuntimeEvent(
            sequence=self._sequence, kind=kind, text=text, role=role,
            messages=tuple(tuple(m) for m in messages),
            run_id=self._snapshot.run.run_id if self._snapshot.run else None,
        ))

    def _notice(self, text: str, role: str = "Error", *, session_id: str | None = None) -> None:
        with self._lock:
            if self.supports_multi_chat and session_id is not None and session_id != self._selected_session_id:
                self._chat_notices.setdefault(session_id, deque(maxlen=32)).append((role, text))
                self._notice_unread.add(session_id)
                self._emit("history_changed")
                return
            self._notices.append((role, text))
            self._emit("message", text, role=role)

    def _ingest(self, frame: dict[str, Any]) -> None:
        if "selection_error" in frame:
            with self._lock:
                if frame.get("selection") == self._selection_generation:
                    self._notice("Could not open that chat; returning to the previous conversation.")
                    previous = frame.get("session_id")
                    if previous:
                        self._select_chat(previous)
            return
        if frame["version"] != API_VERSION:
            raise ValueError("Incompatible server protocol")
        with self._lock:
            if frame.get("multi_chat"):
                self.supports_multi_chat = True
                activity = frame["activity"]
                if activity != self._activity:
                    refresh = (activity.keys() != self._activity.keys() or any(
                        item.get("running") != self._activity.get(key, {}).get("running")
                        for key, item in activity.items()
                    ))
                    self._activity = activity
                    self._emit("history_changed")
                    if refresh:
                        self._read("/v1/sessions", force=True)
                identity = frame["session_id"]
                if self._selected_session_id is None:
                    self._selected_session_id = identity
                    self._chat_notices[identity] = self._notices
                if identity != self._selected_session_id or frame["selection"] != self._selection_generation:
                    return
                self._selection_ready = True
                self._notice_unread.discard(identity)
            changed_server = self._server_id is not None and self._server_id != frame["server_id"]
            if changed_server:
                self._seen.clear()
            if self.supports_multi_chat and self._selected_session_id is not None:
                self._seen[self._selected_session_id] = frame["snapshot"]["sequence"]
            self._server_id = frame["server_id"]
            self._server_cursor = frame["snapshot"]["sequence"]
            self._snapshot = decode_snapshot(frame["snapshot"])
            self._state = display_state(frame["state"])
            self._pending = {
                p["id"]: PendingView(**dict(p, revision=(
                    f"{self._server_id}:{self._selected_session_id}:{p['revision']}"
                    if self.supports_multi_chat else f"{self._server_id}:{p['revision']}"
                )))
                for p in frame["pending"]
            }
            if frame["reset"] or changed_server:
                if changed_server:
                    self._models.clear()
                    self._turns.clear()
                    self._sessions.clear()
                    self._notices.append(("System", "Server restarted. State refreshed; review recovery notices before continuing interrupted work."))
                self._emit("conversation_changed", messages=self._snapshot.messages + tuple(self._notices))
                if self._snapshot.processing:
                    self._emit("run_started")
                if self._snapshot.progress:
                    self._emit("progress", self._snapshot.progress)
            else:
                for event in frame["events"]:
                    self._emit(event["kind"], event["text"], role=event["role"], messages=event["messages"])
            self._emit("state_changed")
            if any(e["kind"] in {"run_finished", "conversation_changed"} for e in frame["events"]):
                self._read("/v1/sessions", force=True)

    def _set_connected(self, connected: bool) -> None:
        with self._lock:
            if connected != self._connected:
                self._connected = connected
                self._emit("connection_changed")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except asyncio.CancelledError:
            pass
        finally:
            self._set_connected(False)

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(headers=headers, timeout=10, trust_env=False) as http:
            while not self._stop.is_set():
                try:
                    parts = urlsplit(self.url)
                    with self._lock:
                        generation = self._selection_generation
                        subscription: dict[str, Any] = {
                            "after": self._server_cursor, "server_id": self._server_id or "",
                            "selection": generation,
                        }
                        if self._selected_session_id is not None:
                            subscription["session_id"] = self._selected_session_id
                    query = urlencode(subscription)
                    url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                                      "/v1/events", query, ""))
                    async with connect(url, additional_headers=headers, open_timeout=5, close_timeout=1,
                                       max_size=16 * 1024 * 1024, proxy=None) as websocket:
                        first = await asyncio.wait_for(websocket.recv(), timeout=10)
                        self._ingest(json.loads(first))
                        self._set_connected(True)
                        self._read("/v1/providers", force=True)
                        self._read("/v1/sessions", force=True)
                        async with asyncio.TaskGroup() as tasks:
                            tasks.create_task(self._receive(websocket))
                            tasks.create_task(self._send(http))
                            if self.supports_multi_chat:
                                tasks.create_task(self._watch_selection(websocket, generation))
                            for _ in range(4):
                                tasks.create_task(self._refresh(http))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Do not print exceptions retaining authenticated requests.
                    self._set_connected(False)
                    await asyncio.sleep(1)

    async def _watch_selection(self, websocket, generation: int) -> None:
        while True:
            with self._lock:
                current = self._selection_generation
                identity = self._selected_session_id
            if current != generation:
                await websocket.send(json.dumps({"session_id": identity, "selection": current}))
                generation = current
            await asyncio.sleep(0.03)

    async def _receive(self, websocket) -> None:
        async for raw in websocket:
            self._ingest(json.loads(raw))
        raise ConnectionError("Event stream closed")

    async def _send(self, http: httpx.AsyncClient) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except Empty:
                await asyncio.sleep(0.03)
                continue
            try:
                await self._post(http, job["body"])
            except asyncio.CancelledError:
                self._notice(f"Request {job['body']['request_id'][:12]}: acknowledgement interrupted. Outcome unknown; inspect state before retrying.",
                             session_id=job["body"].get("session_id"))
                raise

    async def _refresh(self, http: httpx.AsyncClient) -> None:
        while True:
            try:
                job = self._read_jobs.get_nowait()
            except Empty:
                await asyncio.sleep(0.03)
                continue
            await self._fetch(http, job["path"])

    async def _post(self, http: httpx.AsyncClient, body: dict[str, Any]) -> None:
        for attempt in range(2):
            try:
                response = await http.post(self.url + "/v1/commands", json=body)
                data = response.json()
                if not isinstance(data, dict):
                    break
                if response.status_code == 200:
                    if (data.get("server_id") == body["server_id"] and "result" in data
                            and ("session_id" not in body or data.get("session_id") == body["session_id"])):
                        with self._lock:
                            if (self.supports_multi_chat and body["operation"] == "new_chat"
                                    and self._navigation_request == body["request_id"] and self._connected
                                    and self._server_id == body["server_id"]):
                                self._select_chat(data["result"])
                        return
                    break
                if response.status_code >= 400:
                    detail = data.get("detail", "Command rejected")
                    if not isinstance(detail, str):
                        detail = "Invalid command arguments"
                    self._notice(f"Request {body['request_id'][:12]}: {detail}", session_id=body.get("session_id"))
                    return
                break  # Redirects are not acknowledgements; never follow them.
            except httpx.TransportError:
                if attempt == 0:
                    await asyncio.sleep(0.2)
            except ValueError:
                break
        self._notice(f"Request {body['request_id'][:12]}: no acknowledgement. Outcome unknown; inspect state before retrying.",
                     session_id=body.get("session_id"))

    async def _fetch(self, http: httpx.AsyncClient, path: str) -> None:
        try:
            response = await http.get(self.url + path)
            response.raise_for_status()
            data = response.json()
            with self._lock:
                if path == "/v1/providers":
                    self._providers = {key: SimpleNamespace(**p) for key, p in data.items()}
                    self._emit("providers_changed")
                elif path == "/v1/sessions":
                    self._sessions = [SimpleNamespace(**s) for s in data]
                    self._emit("history_changed")
                elif path.endswith("/models"):
                    key = path.split("/")[-2]
                    self._models[key] = data
                    self._emit("models_changed", key)
                else:
                    self._turns[path.split("/")[-2]] = data
                    self._emit("history_changed")
        except (httpx.HTTPError, ValueError):
            self._notice("Could not refresh server catalogue/history; reconnect or reopen the view to retry.")
        finally:
            with self._lock:
                self._reads.discard(path)
                self._read_times[path] = monotonic()

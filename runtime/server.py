"""Authenticated multi-conversation host. Start with python -m runtime.server."""
from __future__ import annotations

import argparse
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict
import hmac
import json
import os
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from runtime.conversations import ConversationManager
from runtime.service import AgentRuntime, RuntimeBusyError
from runtime.wire import API_VERSION, public_frame, public_providers


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MessageArgs(Arguments):
    text: str = Field(min_length=1, max_length=200_000)


class NewChatArgs(Arguments):
    title: str = Field(default="", max_length=500)


class SessionArgs(Arguments):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class DirectoryArgs(Arguments):
    path: str = Field(min_length=1, max_length=32768)


class ModelArgs(Arguments):
    provider_key: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=500)


class SettingArgs(Arguments):
    key: Literal["include_diff", "openai_flex", "openai_reasoning_effort", "anthropic_reasoning_effort"]
    value: bool | Literal["model", "none", "minimal", "low", "medium", "high", "xhigh", "max"] | None


class DecisionArgs(Arguments):
    identity: int = Field(gt=0)
    accept: bool
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


ARGUMENTS: dict[str, type[Arguments]] = {
    "submit": MessageArgs, "new_chat": NewChatArgs, "reset_context": Arguments,
    "reload_context": Arguments,
    "load_chat": SessionArgs, "change_directory": DirectoryArgs,
    "switch_model": ModelArgs, "set_model_setting": SettingArgs,
    "decide_pending": DecisionArgs,
}


class CommandRequest(Arguments):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    server_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    operation: Literal["submit", "new_chat", "reset_context", "reload_context", "load_chat", "change_directory",
                       "switch_model", "set_model_setting", "decide_pending"]
    arguments: dict[str, Any] = Field(default_factory=dict)


class RestartRequest(Arguments):
    server_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    sequence: int = Field(ge=0)


class CommandLedger:
    """Never evict an accepted ID and then accidentally execute it twice."""

    def __init__(self, runtime: AgentRuntime | ConversationManager, server_id: str, capacity: int = 10_000):
        self.runtime, self.server_id, self.capacity = runtime, server_id, capacity
        self._lock = RLock()
        self._results: OrderedDict[str, tuple[str, int, dict[str, Any]]] = OrderedDict()

    def execute(self, command: CommandRequest) -> tuple[int, dict[str, Any]]:
        if command.server_id != self.server_id:
            return 409, {"detail": "Server restarted; refresh state and review before retrying"}
        fingerprint = json.dumps([command.session_id, command.operation, command.arguments], sort_keys=True)
        with self._lock:
            previous = self._results.get(command.request_id)
            if previous:
                old_fingerprint, status, body = previous
                if old_fingerprint != fingerprint:
                    return 409, {"detail": "Request ID already belongs to a different command"}
                return status, body
            if len(self._results) >= self.capacity:
                return 503, {"detail": "Request ledger full; restart the idle server before sending new commands"}
            try:
                arguments = ARGUMENTS[command.operation].model_validate(command.arguments).model_dump()
                if isinstance(self.runtime, ConversationManager):
                    if command.session_id is None:
                        raise ValueError("An explicit chat ID is required")
                    result = self.runtime.execute(command.session_id, command.operation, arguments)
                elif command.operation == "decide_pending":
                    result = self.runtime.decide_file_pending(**arguments)
                else:
                    result = getattr(self.runtime, command.operation)(**arguments)
                status, body = 200, {"result": result, "server_id": self.server_id}
                if isinstance(self.runtime, ConversationManager):
                    body["session_id"] = command.session_id
            except ValidationError:
                status, body = 422, {"detail": "Invalid command arguments"}
            except RuntimeBusyError:
                status, body = 409, {"detail": "This chat is busy or the backend parallel-run limit was reached"}
            except PermissionError:
                status, body = 403, {"detail": "Operation is not permitted on this host"}
            except (ValueError, KeyError):
                status, body = 409, {"detail": "Command rejected; refresh state and review its arguments"}
            except Exception:
                # Partial effects are possible: cache failure without retrying it.
                status, body = 500, {"detail": "Command failed; outcome may be unknown. Inspect state before retrying"}
            self._results[command.request_id] = fingerprint, status, body
            return status, body


def create_server(
    runtime: AgentRuntime | ConversationManager, *, token: str, allowed_hosts: list[str] | None = None,
    ledger_capacity: int = 10_000,
) -> FastAPI:
    if len(token) < 32 or token.strip() != token or not token.isascii():
        raise ValueError("AI_AGENT_TOKEN must be an ASCII token of at least 32 characters")
    multi_chat = isinstance(runtime, ConversationManager)
    if isinstance(runtime, AgentRuntime):
        runtime.disable_privileged_operations()
    server_id = uuid4().hex
    ledger = CommandLedger(runtime, server_id, ledger_capacity)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await asyncio.to_thread(runtime.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.server_id = server_id
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts or ["localhost", "127.0.0.1", "[::1]"],
    )

    def authorized(headers: Any) -> bool:
        value = headers.get("authorization", "")
        return not headers.get("origin") and hmac.compare_digest(
            value.encode("utf-8"), f"Bearer {token}".encode("ascii"),
        )

    def authenticate(request: Request) -> None:
        if not authorized(request.headers):
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def selected_runtime(session_id: str | None = None) -> AgentRuntime:
        if isinstance(runtime, ConversationManager):
            return runtime.get(session_id or runtime.default_chat_id)
        return runtime

    def conversation_frame(session_id: str | None = None, cursor: int | None = None,
                           selection: int = 0):
        selected = selected_runtime(session_id)
        frame = public_frame(selected, server_id, cursor)
        if isinstance(runtime, ConversationManager):
            frame.update(multi_chat=True, session_id=selected.state.chat_session_id,
                         selection=selection, activity=runtime.activity())
        return frame

    @app.get("/v1/health", dependencies=[Depends(authenticate)])
    def health():
        closed = (runtime.maintenance_status()["closed"] if isinstance(runtime, ConversationManager)
                  else runtime.snapshot().closed)
        return {"version": API_VERSION, "server_id": server_id, "closed": closed}

    def local_maintenance(request: Request) -> None:
        authenticate(request)
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(403, "Maintenance requires a direct loopback connection")

    @app.get("/v1/maintenance", dependencies=[Depends(local_maintenance)])
    def maintenance_status():
        if isinstance(runtime, ConversationManager):
            return {"version": API_VERSION, "server_id": server_id, "process_id": os.getpid(),
                    **runtime.maintenance_status()}
        with runtime._condition:
            current = runtime.snapshot()
            return {"version": API_VERSION, "server_id": server_id, "process_id": os.getpid(),
                    "sequence": current.sequence, "processing": current.processing,
                    "pending_count": len(runtime.pending()), "closed": current.closed,
                    "durable_state": runtime._store is not None}

    @app.post("/v1/maintenance/drain", dependencies=[Depends(local_maintenance)])
    def drain_for_restart(request: RestartRequest):
        if request.server_id != server_id:
            raise HTTPException(409, "Server changed; review before restarting")
        try:
            runtime.prepare_restart(request.sequence)
        except (RuntimeBusyError, ValueError):
            raise HTTPException(409, "Runtime is busy or changed; review before restarting") from None
        return {"server_id": server_id, "closed": True}

    @app.get("/v1/snapshot", dependencies=[Depends(authenticate)])
    def snapshot(session_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$")):
        try:
            return conversation_frame(session_id)
        except (ValueError, KeyError):
            raise HTTPException(404, "Unknown chat") from None

    @app.get("/v1/providers", dependencies=[Depends(authenticate)])
    def providers():
        return public_providers(runtime)

    @app.get("/v1/providers/{provider_key}/models", dependencies=[Depends(authenticate)])
    def models(provider_key: str):
        if provider_key not in runtime.providers:
            raise HTTPException(404, "Unknown provider")
        return runtime.provider_models(provider_key)

    @app.get("/v1/sessions", dependencies=[Depends(authenticate)])
    def sessions(limit: int = Query(default=200, ge=1, le=200)):
        return [asdict(session) for session in runtime.list_sessions(limit)]

    @app.get("/v1/sessions/{session_id}/turns", dependencies=[Depends(authenticate)])
    def turns(session_id: str):
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise HTTPException(404, "Unknown session")
        return [{"user": t.get("user", ""), "assistant_final": t.get("assistant_final", "")}
                for t in runtime.load_original_turns(session_id)]

    @app.post("/v1/commands", dependencies=[Depends(authenticate)])
    def command(request: CommandRequest):
        status, body = ledger.execute(request)
        return JSONResponse(body, status_code=status)

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket):
        if not authorized(websocket.headers):
            await websocket.close(code=1008)
            return
        selected = None
        client_id = None
        try:
            await websocket.accept()
            session_id = websocket.query_params.get("session_id") or None
            selection = int(websocket.query_params.get("selection", "0"))
            selected = await asyncio.to_thread(selected_runtime, session_id)
            session_id = selected.state.chat_session_id if multi_chat else None
            client_id = selected.attach_client(can_approve=False)
            try:
                cursor = int(websocket.query_params["after"])
            except (KeyError, ValueError):
                cursor = None
            if websocket.query_params.get("server_id") != server_id:
                cursor = None
            previous = None
            while True:
                frame = await asyncio.to_thread(conversation_frame, session_id, cursor, selection)
                marker = (frame["snapshot"]["sequence"], frame["state"], frame["pending"], frame.get("activity"))
                if marker != previous:
                    await websocket.send_json(frame)
                    previous = marker
                    cursor = frame["snapshot"]["sequence"]
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.15)
                    if not multi_chat:
                        continue
                    request: Any = None
                    try:
                        request = json.loads(raw)
                        next_selection = request["selection"]
                        if type(next_selection) is not int or next_selection <= selection:
                            raise ValueError("Invalid selection")
                        if request.get("session_id") is None:
                            raise ValueError("Chat ID is required")
                        target = await asyncio.to_thread(selected_runtime, request["session_id"])
                    except (KeyError, TypeError, ValueError):
                        await websocket.send_json({"selection_error": "Unknown chat selection",
                                                   "selection": request.get("selection") if isinstance(request, dict) else None,
                                                   "session_id": session_id})
                        continue
                    selected.detach_client(client_id)
                    selected = target
                    client_id = selected.attach_client(can_approve=False)
                    session_id = selected.state.chat_session_id
                    selection = next_selection
                    cursor, previous = None, None
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            if selected is not None and client_id is not None:
                selected.detach_client(client_id)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--max-parallel-runs", type=int, default=4)
    args = parser.parse_args()
    token = os.environ.get("AI_AGENT_TOKEN", "")
    if len(token) < 32:
        parser.error("Set AI_AGENT_TOKEN to a strong random token (at least 32 characters)")
    from runtime.bootstrap import create_conversation_manager
    import uvicorn
    app = create_server(
        create_conversation_manager(durable=True, max_parallel_runs=args.max_parallel_runs), token=token,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", *args.allowed_host],
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()

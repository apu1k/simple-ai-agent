"""UI-independent ownership of one live agent conversation and its execution."""
from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass, replace
from threading import Condition, RLock, Thread
from typing import Callable, Literal
from uuid import uuid4

from core.agent import Agent
from core.tool_artifacts import is_internal_tool_artifact
from core.tool_progress import (
    PRIVILEGED_APPROVAL_PREFIX,
    PRIVILEGED_EVIDENCE_PREFIX,
    approval_ui_context,
)
from editing.model import PendingEdit
from llm.base import LLMClient
from llm.request_progress import REQUEST_PROGRESS_PREFIX
from runtime.bootstrap import build_model_config_and_client, create_agent
from runtime.chat_store import (
    DEFAULT_CHAT_TURN_LIMIT,
    ensure_chat_session,
    record_final_turn,
    start_new_chat,
)
from runtime.privileged_turn import ELEVATED_OPERATION, PendingPrivilege
from runtime.prompt import build_system_prompt
from runtime.state import (
    AgentState,
    ModelSettingValue,
    OPENAI_REASONING_EFFORTS,
)


class RuntimeBusyError(RuntimeError):
    pass


class EventHistoryExpired(ValueError):
    """The client must fetch a snapshot instead of replaying this cursor."""


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    kind: str
    text: str = ""
    role: str = ""
    run_id: str | None = None
    messages: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    user_text: str
    status: Literal["running", "completed", "failed"] = "running"
    reply: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RuntimeSnapshot:
    sequence: int
    messages: tuple[tuple[str, str], ...]
    run: RunInfo | None
    progress: str
    closed: bool

    @property
    def processing(self) -> bool:
        return self.run is not None and self.run.status == "running"


class AgentRuntime:
    """Own an Agent, not a UI worker. Clients consume snapshots and events.

    This first extraction is in-process and volatile. The process hosting this
    object owns its lifetime; disconnecting a client never cancels ordinary
    work. Privilege grants remain volatile and require a live trusted client.
    """

    def __init__(
        self,
        *,
        state: AgentState,
        llm: LLMClient,
        agent_factory: Callable[..., Agent] | None = None,
        history_recorder: Callable[..., int] | None = None,
        event_limit: int = 2048,
    ) -> None:
        if event_limit < 1:
            raise ValueError("event_limit must be positive")
        self.state = state
        self.llm = llm
        self._agent_factory = agent_factory or create_agent
        self._history_recorder = history_recorder or record_final_turn
        self._agent: Agent | None = None
        self._condition = Condition(RLock())
        self._events: deque[RuntimeEvent] = deque(maxlen=event_limit)
        self._sequence = 0
        self._messages: list[tuple[str, str]] = []
        self._run: RunInfo | None = None
        self._worker: Thread | None = None
        self._progress = ""
        self._closed = False
        self._clients: dict[str, bool] = {}

    def initialize(self) -> None:
        with self._condition:
            self._require_open()
            if self._agent is None:
                self._agent = self._agent_factory(
                    state=self.state,
                    llm=self.llm,
                    on_debug=lambda text: self._publish("debug", text),
                    on_tool=self._on_tool,
                    on_raw=lambda text: self._publish("raw", text),
                    on_error=lambda text: self._publish("error", text),
                )

    def attach_client(self, *, can_approve: bool = False) -> str:
        """Register a trusted adapter, not a model-selected authorization."""
        with self._condition:
            self._require_open()
            identity = uuid4().hex
            self._clients[identity] = can_approve
            return identity

    def detach_client(self, identity: str) -> None:
        with self._condition:
            was_approver = self._clients.pop(identity, False)
            if was_approver and not any(self._clients.values()):
                self.state.privileged_turn.revoke()
                self._publish("state_changed")

    def snapshot(self) -> RuntimeSnapshot:
        with self._condition:
            return RuntimeSnapshot(
                sequence=self._sequence,
                messages=tuple(self._messages),
                run=self._run,
                progress=self._progress,
                closed=self._closed,
            )

    def events_since(self, sequence: int) -> tuple[RuntimeEvent, ...]:
        with self._condition:
            if sequence < 0 or sequence > self._sequence:
                raise ValueError("Invalid runtime event cursor")
            if self._events and sequence < self._events[0].sequence - 1:
                raise EventHistoryExpired("Runtime event history expired; fetch a snapshot")
            return tuple(event for event in self._events if event.sequence > sequence)

    def submit(self, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Message must not be empty")
        with self._condition:
            self._require_idle()
            self.initialize()
            # Select the session before accepting work; it cannot change mid-run.
            ensure_chat_session(self.state)
            self._run = RunInfo(run_id=uuid4().hex, user_text=text)
            self._progress = ""
            self._message("You", text)
            self._publish("run_started")
            self._worker = Thread(
                target=self._execute,
                args=(text, any(self._clients.values())),
                name=f"agent-run-{self._run.run_id[:12]}",
                daemon=True,
            )
            try:
                self._worker.start()
            except Exception as error:
                self._fail_run(error)
                raise
            return self._run.run_id

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._is_processing(), timeout)

    def close(self, *, wait: bool = True) -> None:
        """Stop accepting work; revoke privilege, but do not claim tool cancellation."""
        with self._condition:
            self._closed = True
            self._clients.clear()
            self.state.privileged_turn.revoke()
            worker = self._worker
            self._publish("state_changed")
        if wait and worker is not None and worker.ident is not None:
            worker.join()

    def new_chat(self, title: str = "") -> str:
        with self._condition:
            self._require_idle()
            self.initialize()
            identity = start_new_chat(self.state, title=title)
            self._reset_agent()
            self._replace_messages([])
            self._message("System", f"Started new chat session: {identity}")
            return identity

    def reset_context(self) -> None:
        with self._condition:
            self._require_idle()
            self.initialize()
            self._reset_agent()
            self._message("System", "Conversation context reset.")

    def load_chat(self, session_id: str) -> None:
        with self._condition:
            self._require_idle()
            if not any(s.session_id == session_id for s in self.state.chat_store.list_sessions(limit=0)):
                raise ValueError("Unknown chat session")
            turns = self.state.chat_store.load_original_turns(
                session_id, limit=DEFAULT_CHAT_TURN_LIMIT,
            )
            self.initialize()
            warnings: list[str] = []
            latest = turns[-1].get("state", {}) if turns else {}
            if isinstance(latest, dict) and latest.get("provider_key") and latest.get("model"):
                try:
                    self.switch_model(str(latest["provider_key"]), str(latest["model"]))
                except Exception as error:
                    warnings.append(f"Failed to restore provider/model from chat state: {error}")
            self.state.chat_session_id = session_id
            self._reset_agent()
            assert self._agent is not None
            messages: list[tuple[str, str]] = []
            for turn in turns:
                user = str(turn.get("user", ""))
                assistant = str(turn.get("assistant_final", ""))
                self._agent.messages.extend((
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ))
                messages.extend((("You", user), ("AI", assistant)))
            self._replace_messages(messages)
            for warning in warnings:
                self._message("Error", warning)
            self._message("System", f"Loaded chat session: {session_id}")

    def switch_model(self, provider_key: str, model: str) -> None:
        from llm.providers import PROVIDERS

        with self._condition:
            self._require_idle()
            provider = PROVIDERS.get(provider_key)
            if provider is None:
                raise ValueError(f"Unknown provider: {provider_key}")
            config, llm = build_model_config_and_client(provider, model)
            self.initialize()
            assert self._agent is not None
            previous_config, previous_llm = self.state.model_config, self.llm
            self.state.model_config = config
            try:
                self._agent.set_llm(llm, system_prompt=self._system_prompt(llm))
            except Exception:
                self.state.model_config = previous_config
                self._agent.set_llm(previous_llm, system_prompt=self._system_prompt(previous_llm))
                raise
            self.llm = llm
            # A model switch must not transfer an unused next-turn privilege grant.
            self.state.privileged_turn.revoke()
            self._publish("state_changed")

    def change_directory(self, path: str) -> str:
        from tools.fs.read import cd

        with self._condition:
            self._require_idle()
            result = cd(self.state, path)
            role = "Error" if result.startswith("Error:") else "System"
            self._message(role, result)
            self._publish("state_changed")
            return result

    def set_model_setting(
        self, key: str, value: ModelSettingValue, *, client_id: str | None = None,
    ) -> None:
        with self._condition:
            self._require_open()
            revoking = key == "elevated_commands" and value is False
            if self._is_processing() and not revoking:
                raise RuntimeBusyError("Cannot change model settings while AI is processing (except revoking elevation).")
            if key == "elevated_commands" and isinstance(value, bool):
                if value:
                    self._require_approver(client_id)
                    self.state.privileged_turn.arm(ELEVATED_OPERATION)
                else:
                    self.state.privileged_turn.revoke()
            elif key == "include_diff" and (isinstance(value, bool) or value == "model"):
                self.state.model_settings.include_diff = value
            elif key == "openai_flex" and isinstance(value, bool):
                self.state.model_settings.openai_flex = value
            elif key == "openai_reasoning_effort" and (value is None or value in OPENAI_REASONING_EFFORTS):
                self.state.model_settings.openai_reasoning_effort = value
            else:
                raise ValueError(f"Invalid model setting: {key}={value!r}")
            self._publish("state_changed")

    def pending(self) -> dict[int | str, PendingEdit | PendingPrivilege]:
        with self._condition:
            entries: dict[int | str, PendingEdit | PendingPrivilege] = {
                identity: deepcopy(edit)
                for identity, edit in self.state.edit_store.pending().items()
            }
            entries.update(self.state.privileged_turn.pending())
            return entries

    def decide_pending(
        self, identity: int | str, *, accept: bool, client_id: str | None = None,
    ) -> str:
        with self._condition:
            self._require_open()
            if isinstance(identity, str):
                self._require_approver(client_id)
                decision = self.state.privileged_turn.decide(identity, accept=accept)
                suffix = ("Acceptance is not execution; Windows UAC follows if still eligible."
                          if accept else "No execution.")
                message = f"Administrator request #{identity}: {decision}. {suffix}"
                self._message("Approval", message)
            else:
                operation = self.state.edit_store.approve if accept else self.state.edit_store.reject
                message = operation(identity)
                self._message("System", message)
                if accept:
                    cwd_message = self._ensure_existing_cwd()
                    if cwd_message:
                        self._message("System", cwd_message)
            self._publish("state_changed")
            return message

    def _execute(self, text: str, approval_available: bool) -> None:
        try:
            assert self._agent is not None
            with approval_ui_context() if approval_available else nullcontext():
                reply = self._agent.step(text)
            try:
                self._history_recorder(self.state, text, reply)
            except Exception as error:
                with self._condition:
                    self._message("System", f"Warning: chat history could not be saved: {error}")
            with self._condition:
                self._message("AI", reply)
                assert self._run is not None
                self._run = replace(self._run, status="completed", reply=reply)
                self._progress = ""
                self._publish("run_finished")
        except Exception as error:
            with self._condition:
                self._fail_run(error)
        finally:
            with self._condition:
                self._condition.notify_all()

    def _fail_run(self, error: Exception) -> None:
        assert self._run is not None
        self._run = replace(self._run, status="failed", error=str(error))
        self._progress = ""
        self._message("Error", str(error))
        self._publish("run_finished")
        self._condition.notify_all()

    def _on_tool(self, text: str) -> None:
        with self._condition:
            self._publish("tool", text)
            if text.startswith(REQUEST_PROGRESS_PREFIX):
                self._message("System", text[len(REQUEST_PROGRESS_PREFIX):])
            elif text.startswith(PRIVILEGED_APPROVAL_PREFIX):
                identity = text[len(PRIVILEGED_APPROVAL_PREFIX):]
                self._message(
                    "Approval", f"Administrator approval required — request #{identity}. "
                    "Open \\pending (or F9) to review and accept or reject. Nothing has executed.",
                )
                self._publish("approval_required", identity)
            elif text.startswith(PRIVILEGED_EVIDENCE_PREFIX):
                if not self._progress:
                    self._message(
                        "System", "Privileged request progress appears above the chat. "
                        "Progress is not proof of execution, completion, or cleanup.",
                    )
                self._progress = text[len(PRIVILEGED_EVIDENCE_PREFIX):]
                self._publish("progress", self._progress)

    def _publish(
        self, kind: str, text: str = "", *, role: str = "",
        messages: tuple[tuple[str, str], ...] = (),
    ) -> None:
        with self._condition:
            self._sequence += 1
            self._events.append(RuntimeEvent(
                sequence=self._sequence, kind=kind, text=text, role=role,
                run_id=self._run.run_id if self._run is not None else None,
                messages=messages,
            ))

    def _message(self, role: str, text: str) -> None:
        if role == "AI" and is_internal_tool_artifact(text):
            return
        self._messages.append((role, text))
        self._publish("message", text, role=role)

    def _replace_messages(self, messages: list[tuple[str, str]]) -> None:
        self._messages = messages
        self._run = None
        self._progress = ""
        self._publish("conversation_changed", messages=tuple(messages))

    def _is_processing(self) -> bool:
        return self._run is not None and self._run.status == "running"

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Agent runtime is closed")

    def _require_idle(self) -> None:
        self._require_open()
        if self._is_processing():
            raise RuntimeBusyError("Another agent run is already active")

    def _require_approver(self, identity: str | None) -> None:
        if identity is None or not self._clients.get(identity, False):
            raise PermissionError("A connected approval-capable client is required")

    def _system_prompt(self, llm: LLMClient) -> str:
        assert self._agent is not None
        return build_system_prompt(
            self.state,
            use_native_tools=getattr(llm, "supports_native_tools", False),
            tool_registry=self._agent.registry,
        )

    def _reset_agent(self) -> None:
        assert self._agent is not None
        self._agent.reset(self._system_prompt(self.llm))

    def _ensure_existing_cwd(self) -> str | None:
        cwd = self.state.cwd
        original = cwd
        while True:
            try:
                if cwd.is_dir():
                    if cwd != original:
                        self.state.cwd = cwd
                        return f"Current directory was removed. Moved up to: {cwd}"
                    return None
            except OSError:
                pass
            if cwd.parent == cwd:
                return f"Warning: current directory was removed and no existing parent could be found: {original}"
            cwd = cwd.parent

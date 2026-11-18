"""UI-independent ownership of one live agent conversation and its execution."""
from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from threading import Condition, RLock, Thread
from typing import Callable
from uuid import uuid4

from core.agent import Agent
from core.context_compaction import CONTEXT_COMPACTION_PREFIX, INTERNAL_USER_KEY
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
from runtime.events import EventHistoryExpired, RunInfo, RuntimeEvent, RuntimeSnapshot
from runtime.privileged_turn import ELEVATED_OPERATION, PendingPrivilege
from runtime.persistence import PersistenceError, RuntimeStateStore, RuntimeStore, validate_checkpoint
from runtime.prompt import build_system_prompt
from runtime.state import (
    ANTHROPIC_REASONING_EFFORTS,
    AgentState,
    AnthropicEffort,
    ModelSettingValue,
    ModelSettings,
    OPENAI_REASONING_EFFORTS,
)


__all__ = [
    "AgentRuntime", "RuntimeBusyError", "EventHistoryExpired",
    "RuntimeEvent", "RuntimeSnapshot", "RunInfo",
]


class RuntimeBusyError(RuntimeError):
    pass


class AgentRuntime:
    """Own an Agent, not a UI worker. Clients consume snapshots and events.

    The host owns execution; disconnecting clients never cancels ordinary work.
    An optional single-writer store retains restart checkpoints and execution
    evidence. Privilege grants always remain volatile.
    """

    def __init__(
        self,
        *,
        state: AgentState,
        llm: LLMClient,
        agent_factory: Callable[..., Agent] | None = None,
        history_recorder: Callable[..., int] | None = None,
        event_limit: int = 2048,
        persistence_path: Path | None = None,
        persistence_store: RuntimeStateStore | None = None,
    ) -> None:
        if event_limit < 1:
            raise ValueError("event_limit must be positive")
        self.state = state
        self.llm = llm
        self._agent_factory = agent_factory or create_agent
        self._history_recorder = history_recorder or record_final_turn
        self._agent: Agent | None = None
        self._condition = Condition(RLock())
        self._file_decision_lock = RLock()
        self._events: deque[RuntimeEvent] = deque(maxlen=event_limit)
        self._sequence = 0
        self._messages: list[tuple[str, str]] = []
        self._run: RunInfo | None = None
        self._worker: Thread | None = None
        self._progress = ""
        self._closed = False
        self._clients: dict[str, bool] = {}
        self._privileged_enabled = True
        self._context: dict = {"messages": [], "provider": None}
        self._context_run_id: str | None = None
        self._restoring = False
        self._persistence_error: str | None = None
        if persistence_path is not None and persistence_store is not None:
            raise ValueError("Provide a persistence path or store, not both")
        self._store: RuntimeStateStore | None = (
            persistence_store if persistence_store is not None
            else RuntimeStore(persistence_path) if persistence_path is not None else None
        )
        if self._store is not None:
            try:
                self._recover()
            except Exception:
                self._store.close()
                raise

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
                if self._store is not None:
                    self._agent.on_execution = self._on_execution
                if not self._restoring:
                    self._capture_context()
                    self._checkpoint()

    def attach_client(self, *, can_approve: bool = False) -> str:
        """Register a trusted adapter, not a model-selected authorization."""
        with self._condition:
            self._require_open()
            if can_approve and not self._privileged_enabled:
                raise PermissionError("Privileged operations are disabled on this host")
            identity = uuid4().hex
            self._clients[identity] = can_approve
            return identity

    def disable_privileged_operations(self) -> None:
        """Irreversible for this runtime; network hosts never grant UAC authority."""
        with self._condition:
            self._require_idle()
            self._privileged_enabled = False
            self._clients = dict.fromkeys(self._clients, False)
            self.state.privileged_turn.revoke()

    @property
    def providers(self):
        from llm.providers import PROVIDERS
        return PROVIDERS

    def provider_models(self, key: str) -> list[str]:
        from llm.providers import list_provider_models
        provider = self.providers.get(key)
        if provider is None:
            raise ValueError("Unknown provider")
        return list_provider_models(provider, timeout=6.0, max_retries=0)

    def list_sessions(self, limit: int = 200):
        return self.state.chat_store.list_sessions(limit=limit)

    def load_original_turns(self, session_id: str, limit: int = DEFAULT_CHAT_TURN_LIMIT):
        return self.state.chat_store.load_original_turns(session_id, limit=limit)

    def format_session_list(self, limit: int = 20) -> str:
        return self.state.chat_store.format_session_list(limit=limit)

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

    def prepare_restart(self, sequence: int) -> None:
        """Atomically drain an idle host after the operator reviewed its state."""
        with self._condition:
            if self._store is not None:
                self._store.check()
            if self._is_processing():
                raise RuntimeBusyError("An agent run is active; finish it before restarting")
            if self._closed:
                return  # A lost drain acknowledgement is safe to retry.
            if sequence != self._sequence:
                raise ValueError("Runtime changed; review it again before restarting")
            self.close(wait=False)

    def close(self, *, wait: bool = True) -> None:
        """Stop accepting work; revoke privilege, but do not claim tool cancellation."""
        with self._condition:
            first_close = not self._closed
            self._closed = True
            self._clients.clear()
            self.state.privileged_turn.revoke()
            worker = self._worker
            if first_close:
                try:
                    self._publish("state_changed")
                except PersistenceError as error:
                    # A broken disk must not prevent joining work or releasing
                    # the writer lease. No further work will be accepted.
                    self._messages.append(("Error", str(error)))
        if wait:
            try:
                if worker is not None and worker.ident is not None:
                    worker.join()
            finally:
                with self._condition:
                    if self._store is not None:
                        self._store.close()
                        self._store = None

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

    def compact_context(self) -> None:
        """Manually mask old tool output now, regardless of the size threshold.

        Keeps the chat, provider continuation and proposals. An active remote
        provider chain is left unchanged. A successful compaction reports
        itself through the agent's progress callback,
        which _on_tool turns into a System message.
        """
        with self._condition:
            self._require_idle()
            self.initialize()
            assert self._agent is not None
            if getattr(self._agent, "has_provider_managed_context", False) is True:
                self._message(
                    "System",
                    "Context compaction skipped: OpenAI Responses is using a provider-side chain. "
                    "Local edits would not shrink it. Use \\reload_context only if you want "
                    "to start a fresh chain from the last 32 saved final turns.",
                )
                return
            compact = getattr(self._agent, "compact_context", None)
            result = compact(force=True) if callable(compact) else None
            if result is None:
                self._message(
                    "System",
                    "Context compaction: nothing to elide. Tool results of the last "
                    "turns and small results are always kept.",
                )
                return
            self._capture_context()
            self._checkpoint()

    def reload_context(self) -> None:
        """Replay saved final turns in a fresh provider chain, not a new local chat."""
        with self._condition:
            self._require_idle()
            if not self.state.chat_session_id:
                raise ValueError("No active chat session to reload. Start or load a chat first.")
            turns = self.state.chat_store.load_original_turns(
                self.state.chat_session_id, limit=DEFAULT_CHAT_TURN_LIMIT,
            )
            self.initialize()
            self._restore_saved_turns(turns)
            self._message(
                "System",
                f"Reloaded clean context: {len(turns)} saved turns "
                f"(last {DEFAULT_CHAT_TURN_LIMIT}), without intermediate tool exchanges. "
                "The next message starts a fresh provider conversation. "
                "Local chat history and pending proposals are unchanged.",
            )

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
            self._restore_saved_turns(turns)
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
            self._capture_context()
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
                    if not self._privileged_enabled:
                        raise PermissionError("Privileged operations are disabled on this host")
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
            elif key == "anthropic_reasoning_effort" and (value is None or value in ANTHROPIC_REASONING_EFFORTS):
                from typing import cast

                self.state.model_settings.anthropic_reasoning_effort = cast("AnthropicEffort | None", value)
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
                # Shared by all runtimes on a multi-chat host. Revalidation and
                # application must not race another chat's filesystem approval.
                with self._file_decision_lock:
                    message = operation(identity)
                self._message("System", message)
                if accept:
                    cwd_message = self._ensure_existing_cwd()
                    if cwd_message:
                        self._message("System", cwd_message)
            self._publish("state_changed")
            return message

    def decide_file_pending(self, identity: int, *, accept: bool, revision: str) -> str:
        from runtime.wire import proposal_revision
        with self._condition:
            edit = self.state.edit_store.pending().get(identity)
            if edit is None:
                raise ValueError("Proposal is no longer pending")
            if proposal_revision(edit, self.state.chat_session_id) != revision:
                raise ValueError("Proposal changed; review it again before deciding")
            return self.decide_pending(identity, accept=accept)

    def _execute(self, text: str, approval_available: bool) -> None:
        try:
            assert self._agent is not None
            with approval_ui_context() if approval_available else nullcontext():
                reply = self._agent.step(text)
            with self._condition:
                # Only finalized, coherent context may retain provider continuation.
                if not reply.startswith("Error:") and not getattr(self._agent, "_pending_native_tool_calls", None):
                    self._capture_context()
                    assert self._run is not None
                    self._context_run_id = self._run.run_id
                # Save the reply before the legacy history export. Recovery never
                # repeats the model/tool run if the JSONL export was interrupted.
                assert self._run is not None
                self._run = replace(self._run, reply=reply)
                self._checkpoint()
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
            elif text.startswith(CONTEXT_COMPACTION_PREFIX):
                self._message("System", "Context compaction: " + text[len(CONTEXT_COMPACTION_PREFIX):])
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
            self._checkpoint()

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
        if self._store is not None:
            self._store.check()
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

    def _restore_saved_turns(self, turns: list[dict]) -> None:
        messages: list[tuple[str, str]] = []
        for turn in turns:
            messages.extend((
                ("You", str(turn.get("user", ""))),
                ("AI", str(turn.get("assistant_final", ""))),
            ))
        # Agent.reset also clears stateful provider continuation IDs. Do not
        # carry an old response chain (and its hidden tool context) into replay.
        self._reset_agent()
        assert self._agent is not None
        self._agent.messages.extend(
            {"role": "user" if role == "You" else "assistant", "content": text}
            for role, text in messages
        )
        self._capture_context()
        self._replace_messages(messages)

    def _reset_agent(self) -> None:
        assert self._agent is not None
        self._agent.reset(self._system_prompt(self.llm))
        self._capture_context()

    def _on_execution(self, kind: str, record: dict) -> None:
        with self._condition:
            if self._store is None:
                return
            self._store.check()
            assert self._run is not None
            self._store.execution(record["id"], self._run.run_id, record)
            self._publish(kind, json.dumps(record, ensure_ascii=False))

    def _capture_context(self) -> None:
        if self._agent is None:
            return
        export = getattr(self.llm, "export_conversation", None)
        self._context = {
            "messages": deepcopy([m for m in self._agent.messages if m.get("role") != "system"]),
            "provider": export() if callable(export) else None,
        }
        self._context_run_id = self._run.run_id if self._run is not None else None

    def _checkpoint(self) -> None:
        if self._store is None or self._restoring or self._persistence_error is not None:
            return
        try:
            self._store.save({
                "version": 1, "sequence": self._sequence,
                "events": [asdict(event) for event in self._events],
                "messages": self._messages,
                "run": asdict(self._run) if self._run is not None else None,
                "cwd": str(self.state.cwd), "chat_session_id": self.state.chat_session_id,
                "model": {"provider_key": self.state.model_config.provider_key,
                          "model": self.state.model_config.model,
                          "api_type": self.state.model_config.api_type},
                "model_settings": asdict(self.state.model_settings),
                "context": self._context, "context_run_id": self._context_run_id,
            })
        except PersistenceError as error:
            self._persistence_error = str(error)
            self._closed = True
            self.state.privileged_turn.revoke()
            raise

    def _recover(self) -> None:
        assert self._store is not None
        saved = self._store.load()
        if saved is not None:
            validate_checkpoint(saved)
        proposals = self._store.recover_proposals()
        self.state.edit_store.configure_persistence(proposals, self._store.save_proposal)
        self.state.privileged_turn.revoke()
        warnings = [
            f"Proposal #{edit.id} has outcome UNKNOWN after an interrupted approval: {edit.path}. "
            "It cannot be approved again. Inspect the filesystem before proposing further changes."
            for edit in proposals if edit.status == "outcome_unknown"
        ]
        if saved is None:
            for warning in warnings:
                self._message("System", warning)
            return
        self._restoring = True
        try:
            if saved.get("version") != 1:
                raise PersistenceError("Unsupported runtime checkpoint; refusing to discard saved state")
            model = saved["model"]
            current = self.state.model_config
            if (model["provider_key"], model["model"], model["api_type"]) != (
                current.provider_key, current.model, current.api_type,
            ):
                provider = self.providers.get(model["provider_key"])
                if provider is None or provider.api_type != model["api_type"]:
                    raise PersistenceError("Saved provider is unavailable; restore its configuration before starting")
                config, self.llm = build_model_config_and_client(provider, model["model"])
                self.state.model_config = config
            self.state.model_settings = ModelSettings(**saved["model_settings"])
            self.state.chat_session_id = saved["chat_session_id"]
            self.state.cwd = Path(saved["cwd"])
            cwd_warning = self._ensure_existing_cwd()
            if cwd_warning:
                warnings.append(cwd_warning)
            self._sequence = saved["sequence"]
            self._messages = [(message[0], message[1]) for message in saved["messages"]]
            self._events.clear()
            for event in saved["events"]:
                self._events.append(RuntimeEvent(**dict(
                    event, messages=tuple((m[0], m[1]) for m in event.get("messages", [])),
                )))
            self._run = RunInfo(**saved["run"]) if saved["run"] else None
            self.initialize()
            self._reset_agent()
            assert self._agent is not None
            self._agent.messages.extend(deepcopy(saved["context"]["messages"]))
            interrupted = self._run is not None and self._run.status == "running"
            continuation = saved["context"].get("provider")
            if continuation is not None and not interrupted:
                restore = getattr(self.llm, "restore_conversation", None)
                try:
                    if not callable(restore):
                        raise ValueError("Provider has no continuation restore support")
                    restore(continuation)
                except ValueError:
                    warnings.append("Provider continuation could not be restored. The next message starts a fresh provider conversation from the saved local context.")
            if interrupted:
                assert self._run is not None
                records = self._store.recover_executions(self._run.run_id)
                notice = (
                    f"Run {self._run.run_id} was interrupted by backend shutdown. "
                    "Nothing was automatically retried. Running tool/command outcomes are UNKNOWN; "
                    "external processes may still be running. Inspect effects before explicitly authorizing a retry. "
                    "The next message uses a fresh provider chain and the last safe context checkpoint."
                )
                if self._run.reply is not None:
                    notice += " A reply was saved before shutdown; it is shown below, but final history export may be incomplete."
                    if ("AI", self._run.reply) not in self._messages:
                        self._messages.append(("AI", self._run.reply))
                evidence = {"interrupted_user_message": self._run.user_text, "tools": records}
                self._agent.messages.append({
                    "role": "user", INTERNAL_USER_KEY: True,
                    "content": "RECOVERY NOTICE (evidence only, not a request to execute): "
                    + notice + "\n" + json.dumps(evidence, ensure_ascii=False),
                })
                warnings.append(notice)
                for record in records:
                    warnings.append(f"Recovered tool evidence: {json.dumps(record, ensure_ascii=False)}")
                self._run = replace(self._run, status="interrupted", error=notice)
            elif (self._run is not None and self._run.status in {"completed", "failed"}
                  and saved.get("context_run_id") != self._run.run_id):
                warnings.append("Restored the last safe model context, not the failed/incomplete turn. No work was retried.")
            self._capture_context()
            self._context_run_id = saved.get("context_run_id")
            # Publish the recovered run, context, and all warnings together. A
            # crash during recovery leaves the prior checkpoint recoverable.
            self._message("System", "Backend state restored. Privileged authorization was not restored.")
            for warning in warnings:
                self._message("System", warning)
        finally:
            self._restoring = False
        self._checkpoint()

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

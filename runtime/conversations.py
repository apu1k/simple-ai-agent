"""One host, independent per-chat runtimes; selection belongs to clients."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from threading import Condition, RLock
from typing import Any, Callable

from runtime.chat_store import ChatStore
from runtime.conversation_store import ConversationStorage, validate_chat_id
from runtime.persistence import PersistenceError, RuntimeStateStore
from runtime.service import AgentRuntime, RuntimeBusyError
from runtime.state import AgentState

RuntimeFactory = Callable[[str, RuntimeStateStore | None, AgentState | None], AgentRuntime]


class ConversationManager:
    supports_multi_chat = True

    def __init__(self, *, history: ChatStore, runtime_factory: RuntimeFactory,
                 persistence_path: Path | None = None, max_parallel_runs: int = 4):
        if max_parallel_runs < 1:
            raise ValueError("max_parallel_runs must be positive")
        self.history = history
        self._factory = runtime_factory
        self.max_parallel_runs = max_parallel_runs
        self._condition = Condition(RLock())
        self._file_decision_lock = RLock()
        self._runtimes: dict[str, AgentRuntime] = {}
        self._closed = False
        self._revision = 0
        self._marker: Any = None
        self.storage = ConversationStorage(persistence_path, history) if persistence_path is not None else None
        try:
            identities = self.storage.ids() if self.storage else []
            default = self.storage.default_chat() if self.storage else None
            if default is not None and default not in identities:
                raise PersistenceError("Default conversation has no checkpoint; inspect storage")
            # Recover previously live chats, not every historical conversation.
            for identity in identities:
                self.get(identity)
            if default is None:
                default = identities[0] if identities else self.new_chat()
                if self.storage:
                    self.storage.set_default(default)
            self.default_chat_id = default
        except Exception:
            self.close()
            raise

    @property
    def providers(self):
        return self.get(self.default_chat_id).providers

    def provider_models(self, key: str) -> list[str]:
        return self.get(self.default_chat_id).provider_models(key)

    def list_sessions(self, limit: int = 200):
        return self.history.list_sessions(limit)

    def load_original_turns(self, session_id: str, limit: int = 32):
        return self.history.load_original_turns(session_id, limit)

    def _require_open(self) -> None:
        if self.storage:
            self.storage.root.check()
        if self._closed:
            raise RuntimeError("Conversation host is closed")

    def get(self, identity: str, *, source: AgentState | None = None) -> AgentRuntime:
        validate_chat_id(identity)
        with self._condition:
            existing = self._runtimes.get(identity)
            if existing is not None:
                return existing
            self._require_open()
            scope = self.storage.scope(identity) if self.storage else None
            saved = scope.load() if scope else None
            if saved is None and not any(s.session_id == identity for s in self.history.list_sessions(limit=0)):
                raise ValueError("Unknown chat session")
            runtime = self._factory(identity, scope, source)
            try:
                if runtime.state.chat_session_id != identity:
                    raise ValueError("Runtime factory returned a different chat")
                runtime._file_decision_lock = self._file_decision_lock
                runtime.disable_privileged_operations()
                if saved is None:
                    # Hydrate old JSONL history once, atomically with the first
                    # checkpoint. Selecting a live chat never rebuilds context.
                    runtime._restoring = True
                    try:
                        runtime.load_chat(identity)
                    finally:
                        runtime._restoring = False
                    runtime._checkpoint()
                else:
                    runtime.initialize()
                self._runtimes[identity] = runtime
                return runtime
            except Exception:
                # Cleanup is not a successful activation. In particular, never
                # turn a failed historical-chat import into an empty durable
                # checkpoint that would suppress hydration on the next attempt.
                runtime._restoring = True
                runtime.close()
                raise

    def new_chat(self, title: str = "", *, source_id: str | None = None) -> str:
        with self._condition:
            self._require_open()
            source = self.get(source_id).state if source_id is not None else None
            identity = self.history.new_session(source, title=title)
            self.get(identity, source=source)
            return identity

    def execute(self, identity: str, operation: str, arguments: dict[str, Any]):
        with self._condition:
            self._require_open()
            runtime = self.get(identity)
            if operation == "new_chat":
                return self.new_chat(source_id=identity, **arguments)
            if operation == "load_chat":
                target = arguments["session_id"]
                self.get(target)
                return target  # No shared selection or context reset.
            if operation == "submit":
                if runtime.snapshot().processing:
                    raise RuntimeBusyError("This chat already has an active run")
                if sum(r.snapshot().processing for r in self._runtimes.values()) >= self.max_parallel_runs:
                    raise RuntimeBusyError("The backend parallel-run limit has been reached")
            if operation == "decide_pending":
                return runtime.decide_file_pending(**arguments)
            if operation not in {"submit", "reset_context", "reload_context", "change_directory",
                                 "switch_model", "set_model_setting"}:
                raise ValueError("Unknown conversation operation")
            return getattr(runtime, operation)(**arguments)

    def activity(self) -> dict[str, dict[str, Any]]:
        with self._condition:
            result = {}
            for identity, runtime in self._runtimes.items():
                with runtime._condition:
                    snapshot = runtime.snapshot()
                    result[identity] = {"sequence": snapshot.sequence,
                                        "running": snapshot.processing,
                                        "pending_count": len(runtime.pending())}
            return result

    def maintenance_status(self) -> dict[str, Any]:
        with self._condition, ExitStack() as locks:
            for runtime in self._runtimes.values():
                locks.enter_context(runtime._condition)
            return self._maintenance_status_locked()

    def _maintenance_status_locked(self) -> dict[str, Any]:
        marker = tuple((identity, runtime.snapshot().sequence,
                        tuple((str(key), repr(edit)) for key, edit in runtime.pending().items()))
                       for identity, runtime in self._runtimes.items())
        if marker != self._marker:
            self._revision += 1
            self._marker = marker
        return {"sequence": self._revision,
                "processing": any(r.snapshot().processing for r in self._runtimes.values()),
                "pending_count": sum(len(r.pending()) for r in self._runtimes.values()),
                "closed": self._closed, "durable_state": self.storage is not None}

    def prepare_restart(self, sequence: int) -> None:
        with self._condition, ExitStack() as locks:
            if self.storage:
                self.storage.root.check()
            if self._closed:
                return
            for runtime in self._runtimes.values():
                locks.enter_context(runtime._condition)
            status = self._maintenance_status_locked()
            if status["processing"]:
                raise RuntimeBusyError("A chat has an active run; finish it before restarting")
            if status["sequence"] != sequence:
                raise ValueError("Conversations changed; review them again before restarting")
            self._closed = True
            for runtime in self._runtimes.values():
                runtime.close(wait=False)

    def close(self, *, wait: bool = True) -> None:
        with self._condition:
            self._closed = True
            runtimes = list(self._runtimes.values())
            for runtime in runtimes:
                runtime.close(wait=False)
        if wait:
            try:
                for runtime in runtimes:
                    runtime.close(wait=True)
            finally:
                if self.storage:
                    self.storage.close()

"""
runtime/chat_store.py

Persistent chat/session history storage.

The store intentionally keeps two streams per chat session:
- original: immutable source-of-truth user/assistant turns
- working:  future AI-context stream, currently written identically to original

The UI can later build a history selector on top of this module without
changing the persistence format or agent loop wiring.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config.settings import PROJECT_ROOT
from core.tool_artifacts import is_internal_tool_artifact

if TYPE_CHECKING:
    from runtime.state import AgentState


CHAT_HISTORY_DIR = PROJECT_ROOT / ".agent_chat_history"
SESSIONS_FILE = "sessions.jsonl"
ORIGINAL_TURNS_FILE = "turns_original.jsonl"
WORKING_TURNS_FILE = "turns_working.jsonl"


def _assert_no_unhandled_tool_call_markup(text: str) -> None:
    """
    Textual <tool_call> blocks are allowed, but they must be consumed by
    core.protocol/core.agent before final assistant text is stored.
    """
    if not isinstance(text, str):
        return

    lowered = text.lower()
    if "<tool_call>" in lowered or "</tool_call>" in lowered:
        raise RuntimeError(
            "Unhandled <tool_call> markup reached assistant_final. "
            "Textual tool calls must be parsed, executed, and stripped before "
            "chat history is persisted."
        )


@dataclass(frozen=True)
class ChatSessionSummary:
    """Small serializable summary for history listings."""

    session_id: str
    created_at: str
    updated_at: str
    title: str
    turn_count: int
    cwd_at_start: str
    provider_label: str
    model: str


class ChatStore:
    """Append-only JSONL chat history store."""

    def __init__(self, root: Path | None = None):
        self.root = root or CHAT_HISTORY_DIR
        self.sessions_path = self.root / SESSIONS_FILE
        self.original_turns_path = self.root / ORIGINAL_TURNS_FILE
        self.working_turns_path = self.root / WORKING_TURNS_FILE
        self._lock = threading.Lock()

    def new_session(self, state: "AgentState | None" = None, title: str = "") -> str:
        """Create a new chat session and return its id."""
        session_id = uuid.uuid4().hex
        now = _utc_now()
        snapshot = _state_snapshot(state)
        record = {
            "type": "session_created",
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "title": title,
            "state": snapshot,
        }
        with self._lock:
            self._append_jsonl(self.sessions_path, record)
        return session_id

    def append_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
        state: "AgentState | None" = None,
    ) -> int:
        """
        Append a completed user/assistant turn to original and working streams.

        Returns the one-based turn index within the session.
        """
        if not session_id:
            raise ValueError("session_id must not be empty")

        _assert_no_unhandled_tool_call_markup(assistant_text)

        with self._lock:
            turn_index = self._next_turn_index_unlocked(session_id)
            now = _utc_now()
            snapshot = _state_snapshot(state)

            original = {
                "type": "turn",
                "stream": "original",
                "session_id": session_id,
                "turn_index": turn_index,
                "created_at": now,
                "user": user_text,
                "assistant_final": assistant_text,
                "state": snapshot,
            }
            working = {
                "type": "turn",
                "stream": "working",
                "session_id": session_id,
                "turn_index": turn_index,
                "created_at": now,
                "source": "original",
                "source_turn_index": turn_index,
                "user": user_text,
                "assistant_final": assistant_text,
                "state": snapshot,
            }

            self._append_jsonl(self.original_turns_path, original)
            self._append_jsonl(self.working_turns_path, working)

        return turn_index

    def list_sessions(self, limit: int = 20) -> list[ChatSessionSummary]:
        """Return recent chat sessions, newest activity first."""
        sessions: dict[str, dict[str, Any]] = {}
        for record in self._read_jsonl(self.sessions_path):
            if record.get("type") != "session_created":
                continue
            session_id = str(record.get("session_id", ""))
            if not session_id:
                continue
            state = record.get("state") if isinstance(record.get("state"), dict) else {}
            sessions[session_id] = {
                "session_id": session_id,
                "created_at": str(record.get("created_at", "")),
                "updated_at": str(record.get("updated_at", record.get("created_at", ""))),
                "title": str(record.get("title", "")),
                "turn_count": 0,
                "cwd_at_start": str(state.get("cwd", "")),
                "provider_label": str(state.get("provider_label", "")),
                "model": str(state.get("model", "")),
            }

        for turn in self._read_jsonl(self.original_turns_path):
            session_id = str(turn.get("session_id", ""))
            if session_id not in sessions:
                continue
            sessions[session_id]["turn_count"] += 1
            sessions[session_id]["updated_at"] = str(turn.get("created_at", sessions[session_id]["updated_at"]))

            # Prefer latest per-turn model/provider so history reflects where the
            # session ended, not only where it started.
            turn_state = turn.get("state") if isinstance(turn.get("state"), dict) else {}
            provider_label = str(turn_state.get("provider_label", "")).strip()
            model = str(turn_state.get("model", "")).strip()
            if provider_label:
                sessions[session_id]["provider_label"] = provider_label
            if model:
                sessions[session_id]["model"] = model

        summaries = [ChatSessionSummary(**data) for data in sessions.values()]
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        if limit > 0:
            return summaries[:limit]
        return summaries

    def load_original_turns(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Load original turns for one session."""
        turns = [
            record
            for record in self._read_jsonl(self.original_turns_path)
            if record.get("session_id") == session_id and record.get("type") == "turn"
        ]
        turns.sort(key=lambda item: int(item.get("turn_index", 0)))
        if limit > 0:
            return turns[-limit:]
        return turns

    def format_session_list(self, limit: int = 20) -> str:
        """Format a compact session list for CLI/Textual command output."""
        sessions = self.list_sessions(limit=limit)
        if not sessions:
            return "No chat history yet."

        lines = ["Recent chat sessions:"]
        for session in sessions:
            title = f" — {session.title}" if session.title else ""
            lines.append(
                f"{session.session_id[:12]} | turns={session.turn_count} | "
                f"updated={session.updated_at} | {session.provider_label} / {session.model}{title}"
            )
        return "\n".join(lines)

    def _next_turn_index_unlocked(self, session_id: str) -> int:
        count = 0
        for record in self._read_jsonl(self.original_turns_path):
            if record.get("session_id") == session_id and record.get("type") == "turn":
                count += 1
        return count + 1

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            f.write("\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
        return records


def ensure_chat_session(state: "AgentState") -> str:
    """Ensure the runtime state has an active chat session id."""
    if not state.chat_session_id:
        state.chat_session_id = state.chat_store.new_session(state)
    return state.chat_session_id


def start_new_chat(state: "AgentState", title: str = "") -> str:
    """Start a new persistent chat session and update state."""
    state.chat_session_id = state.chat_store.new_session(state, title=title)
    return state.chat_session_id


def record_final_turn(state: "AgentState", user_text: str, assistant_text: str) -> int:
    """Record a completed user/assistant turn for the active session."""
    if is_internal_tool_artifact(assistant_text):
        assistant_text = ""

    session_id = ensure_chat_session(state)
    return state.chat_store.append_turn(
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        state=state,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _state_snapshot(state: "AgentState | None") -> dict[str, Any]:
    if state is None:
        return {}

    model_config = state.model_config
    return {
        "cwd": str(state.cwd),
        "provider_key": model_config.provider_key,
        "provider_label": model_config.provider_label,
        "model": model_config.model,
        "api_type": model_config.api_type,
        "pending_edit_count": len(state.edit_store.pending()),
    }

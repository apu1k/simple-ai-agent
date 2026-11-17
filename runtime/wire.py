"""Explicit, credential-free per-conversation wire views."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from types import SimpleNamespace
from typing import Any

from runtime.events import RunInfo, RuntimeEvent, RuntimeSnapshot

API_VERSION = 1


def proposal_revision(edit: Any, session_id: str | None = None) -> str:
    encoded = json.dumps([session_id, asdict(edit)], default=str, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PendingView:
    id: int
    path: str
    kind: str
    status: str
    diff: str
    revision: str


def public_providers(runtime: Any) -> dict[str, dict[str, Any]]:
    return {
        key: {"key": key, "label": p.label, "default_model": p.default_model,
              "supports_model_listing": p.supports_model_listing}
        for key, p in runtime.providers.items()
    }


def public_frame(runtime: Any, server_id: str, cursor: int | None = None) -> dict[str, Any]:
    # Snapshot, display state, pending revisions, and replay cursor are atomic
    # with respect to runtime commands. Never serialize AgentState/ModelConfig.
    from runtime.events import EventHistoryExpired
    with runtime._condition:
        snapshot = runtime.snapshot()
        reset = cursor is None
        events: tuple[RuntimeEvent, ...] = ()
        if not reset:
            try:
                events = runtime.events_since(cursor)
            except (EventHistoryExpired, ValueError):
                reset = True
        state = runtime.state
        model = state.model_config
        pending = [
            asdict(PendingView(
                id=edit.id, path=str(edit.path), kind=edit.kind, status=edit.status,
                diff=edit.diff, revision=proposal_revision(edit, state.chat_session_id),
            ))
            for edit in runtime.pending().values() if isinstance(edit.id, int)
        ]
        return {
            "version": API_VERSION, "server_id": server_id, "reset": reset,
            "snapshot": asdict(snapshot),
            "events": [asdict(event) for event in events],
            "state": {
                "cwd": str(state.cwd), "chat_session_id": state.chat_session_id,
                "model_config": {"provider_key": model.provider_key,
                                 "provider_label": model.provider_label,
                                 "model": model.model, "api_type": model.api_type},
                "model_settings": asdict(state.model_settings),
            },
            "pending": pending,
        }


def display_state(data: dict[str, Any] | None = None) -> SimpleNamespace:
    data = data or {
        "cwd": "Connecting to agent server…", "chat_session_id": None,
        "model_config": {"provider_key": "", "provider_label": "Disconnected",
                         "model": "", "api_type": ""},
        "model_settings": {"include_diff": False, "openai_flex": False,
                           "openai_reasoning_effort": None},
    }
    return SimpleNamespace(
        cwd=data["cwd"], chat_session_id=data["chat_session_id"],
        model_config=SimpleNamespace(**data["model_config"]),
        model_settings=SimpleNamespace(**data["model_settings"]),
        privileged_turn=SimpleNamespace(
            status="disabled (network client)", armed_operation=None,
        ),
    )


def decode_snapshot(data: dict[str, Any]) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        sequence=data["sequence"], messages=tuple(tuple(m) for m in data["messages"]),
        run=RunInfo(**data["run"]) if data["run"] else None,
        progress=data["progress"], closed=data["closed"],
    )

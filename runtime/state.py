"""
runtime/state.py

AgentState holds everything the agent needs at runtime:
  - cwd:             current working directory (updated by cd tool)
  - model_config:    currently selected LLM provider + model
  - edit_store:      owns all pending file edits
  - chat_store:      owns persistent chat/session history
  - chat_session_id: current persistent chat session id (lazily created)

ModelConfig is a plain dataclass; it's updated when the user runs \models.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from editing.store import EditStore
from runtime.chat_store import ChatStore


ApiType = Literal["chat_completions", "responses", "completions", "gemini_vertex"]


@dataclass
class ModelConfig:
    provider_key: str
    provider_label: str
    model: str
    api_key: str | None
    base_url: str | None
    api_type: ApiType
    project: str | None = None
    location: str | None = None


@dataclass
class AgentState:
    cwd: Path
    model_config: ModelConfig
    edit_store: EditStore = field(default_factory=EditStore)
    chat_store: ChatStore = field(default_factory=ChatStore)
    chat_session_id: str | None = None

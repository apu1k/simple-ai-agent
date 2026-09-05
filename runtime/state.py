"""
runtime/state.py

AgentState holds everything the agent needs at runtime:
  - cwd:             current working directory (updated by cd tool)
  - model_config:    currently selected LLM provider + model
  - model_settings:  runtime controls for model-facing behavior
  - edit_store:      owns all pending file edits
  - chat_store:      owns persistent chat/session history
  - chat_session_id: current persistent chat session id (lazily created)

ModelConfig is a plain dataclass; it's updated when the user runs \\models.
ModelSettings is updated through the \\settings Textual UI.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from editing.store import EditStore
from runtime.chat_store import ChatStore
from night_shifts.storage import ToolCallStore


ApiType = Literal["chat_completions", "responses", "completions", "gemini_vertex"]
IncludeDiffSetting = bool | Literal["model"]


@dataclass
class ModelSettings:
    """Runtime settings that control model-facing behavior."""

    # True: always return proposal diffs; False: never return them;
    # "model": honor the tool call's include_diff request (default false).
    include_diff: IncludeDiffSetting = False

    # Opt in to Flex for direct OpenAI Responses/Chat Completions requests.
    # Runtime-only preference; ignored by other providers and APIs.
    openai_flex: bool = False


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
    model_settings: ModelSettings = field(default_factory=ModelSettings)
    edit_store: EditStore = field(default_factory=EditStore)
    chat_store: ChatStore = field(default_factory=ChatStore)
    chat_session_id: str | None = None
    tool_call_store: ToolCallStore | None = None

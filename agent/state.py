from dataclasses import dataclass, field
from pathlib import Path

from agent.pending_edits import PendingEdit
from llm.models import ModelConfig


@dataclass
class AgentState:
    cwd: Path
    model_config: ModelConfig
    pending_edits: dict[int, PendingEdit] = field(default_factory=dict)
    next_pending_edit_id: int = 1
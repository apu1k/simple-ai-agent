from dataclasses import dataclass
from pathlib import Path

from llm.models import ModelConfig


@dataclass
class AgentState:
    cwd: Path
    model_config: ModelConfig
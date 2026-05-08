from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentState:
    cwd: Path
    model: str
"""
core/messages.py

Pure message type definitions.
No logic, no I/O, no imports from this project.
"""

from dataclasses import dataclass, field
from typing import Literal


Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class SystemMessage(Message):
    role: Role = "system"


@dataclass(frozen=True)
class UserMessage(Message):
    role: Role = "user"


@dataclass(frozen=True)
class AssistantMessage(Message):
    role: Role = "assistant"


def as_dict(message: Message) -> dict:
    """Convert a Message to the plain dict format expected by LLM APIs."""
    return {"role": message.role, "content": message.content}


def messages_as_dicts(messages: list[Message]) -> list[dict]:
    return [as_dict(m) for m in messages]

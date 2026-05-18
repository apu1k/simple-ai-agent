"""
llm/base.py

Abstract interface for LLM clients.
Every provider implements this protocol.

To add a new provider:
  1. Create llm/myprovider.py
  2. Implement the LLMClient protocol
  3. Register it in llm/providers.py
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def chat(self, messages: list[dict]) -> str:
        """
        Send a list of messages to the LLM and return the reply as a string.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.

        Returns:
            The model's reply as a plain string.
        """
        ...

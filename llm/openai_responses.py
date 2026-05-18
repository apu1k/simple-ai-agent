"""
llm/openai_responses.py

OpenAI Responses API client.
Implements llm/base.py LLMClient protocol.
"""

from openai import OpenAI
from llm.providers import ProviderConfig


class OpenAIResponsesClient:
    """LLM client using the OpenAI Responses API."""

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model

    def chat(self, messages: list[dict]) -> str:
        instructions, input_messages = self._split_messages(messages)
        response = self._client.responses.create(
            model=self._model,
            instructions=instructions,
            input=input_messages,
        )
        return response.output_text

    @staticmethod
    def _split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
        """Separate system messages (→ instructions) from user/assistant messages."""
        instructions = []
        input_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                instructions.append(msg.get("content", ""))
            else:
                input_messages.append({"role": msg["role"], "content": msg.get("content", "")})
        return "\n\n".join(instructions), input_messages

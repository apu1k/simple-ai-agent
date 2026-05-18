"""
llm/openai_chat.py

OpenAI chat completions client.
Implements llm/base.py LLMClient protocol.
"""

from openai import OpenAI
from llm.providers import ProviderConfig


class OpenAIChatClient:
    """LLM client using the OpenAI chat completions API."""

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model

    def chat(self, messages: list[dict]) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content

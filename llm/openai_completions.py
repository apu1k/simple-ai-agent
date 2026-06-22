"""
llm/openai_completions.py

OpenAI legacy completions API client.
Implements llm/base.py LLMClient protocol.

Used for legacy models like Codex, text-davinci, etc.
Endpoint: /v1/completions (NOT /v1/chat/completions)
"""

from openai import OpenAI
from llm.base import LLMResponse
from llm.providers import ProviderConfig

REQUEST_TIMEOUT_SECONDS = 180.0


class OpenAICompletionsClient:
    """LLM client using the OpenAI legacy completions API.
    
    Note: This API does NOT support native tool calling.
    Tools must be used via JSON parser fallback mode.
    """

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model

    @property
    def supports_native_tools(self) -> bool:
        """Legacy completions API does NOT support native tool calling."""
        return False
    
    @property
    def api_type(self) -> str:
        """Return the API type for this client."""
        return "completions"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None
    ) -> str | LLMResponse:
        """Send messages to OpenAI Completions API and return the response.
        
        Args:
            messages: Conversation history with role/content dicts.
            tools: Ignored (completions API doesn't support native tools).
            tool_choice: Ignored (completions API doesn't support native tools).
        
        Returns:
            String response (completions API always returns text).
        """
        # Convert chat messages to a single prompt string
        prompt = self._messages_to_prompt(messages)
        
        response = self._client.completions.create(
            model=self._model,
            prompt=prompt,
            max_tokens=4096,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        
        # Completions API always returns text, no native tool support
        return response.choices[0].text or ""
    
    def _messages_to_prompt(self, messages: list[dict]) -> str:
        """Convert chat-style messages to a completion prompt.
        
        Legacy completions models expect a single text prompt,
        not a list of role-based messages.
        """
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                parts.append(f"System: {content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
        
        # Add prompt for next response
        parts.append("Assistant:")
        
        return "\n\n".join(parts)

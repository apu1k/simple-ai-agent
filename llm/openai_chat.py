"""
llm/openai_chat.py

OpenAI chat completions client.
Implements llm/base.py LLMClient protocol.
"""

import json

from openai import OpenAI
from llm.base import LLMResponse, NativeToolCall
from llm.providers import ProviderConfig

REQUEST_TIMEOUT_SECONDS = 180.0


class OpenAIChatClient:
    """LLM client using the OpenAI chat completions API."""

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model

    @property
    def supports_native_tools(self) -> bool:
        """OpenAI Completions API supports native tool calling."""
        return True
    
    @property
    def supports_native_tool_outputs(self) -> bool:
        """Chat Completions client does not use structured tool-output continuation."""
        return False

    def submit_tool_outputs(self, tool_outputs):
        """Unsupported for Chat Completions API.

        Tool results are continued via message replay, not function_call_output items.
        """
        raise NotImplementedError("OpenAIChatClient does not support submit_tool_outputs().")

    @property
    def api_type(self) -> str:
        """Return the API type for this client."""
        return "chat_completions"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None
    ) -> str | LLMResponse:
        """Send messages to OpenAI and return the response.
        
        Args:
            messages: Conversation history with role/content dicts.
            tools: Optional tool definitions for native tool calling.
            tool_choice: How to use tools ("auto", "required", "none", or specific).
        
        Returns:
            LLMResponse with tool_calls if tools were called,
            or str for content-only responses.
        """
        # Build request kwargs
        kwargs = {
            "model": self._model,
            "messages": messages,
            "timeout": REQUEST_TIMEOUT_SECONDS,
        }
        
        # Add native tool parameters if provided
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        
        response = self._client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        
        # Check for native tool calls
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    raw_args = raw_args.strip()
                    arguments = json.loads(raw_args) if raw_args else {}
                elif isinstance(raw_args, dict):
                    arguments = raw_args
                elif raw_args is None:
                    arguments = {}
                else:
                    raise TypeError(f"Invalid tool arguments type: {type(raw_args).__name__}")
                    
                if not isinstance(arguments, dict):
                    raise TypeError("Tool arguments must decode to a JSON object")
                    
                tool_calls.append(
                    NativeToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    )
                )
                
            return LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
            )

        # No tool calls - return content as string (backward compat)
        return message.content or ""

"""
llm/openai_responses.py

OpenAI Responses API client.
Implements llm/base.py LLMClient protocol.
"""

import json
import sys

from openai import OpenAI
from llm.base import LLMResponse, NativeToolCall, NativeToolOutput
from llm.providers import ProviderConfig
from config.settings import DEBUG_LOGS

REQUEST_TIMEOUT_SECONDS = 180.0


class OpenAIResponsesClient:
    """LLM client using the OpenAI Responses API."""

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model
        self._last_response_id: str | None = None

    @property
    def supports_native_tools(self) -> bool:
        """OpenAI Responses API supports native tool calling."""
        return True
    
    @property
    def supports_native_tool_outputs(self) -> bool:
        """Responses API supports structured tool-output continuation."""
        return True

    @property
    def api_type(self) -> str:
        """Return the API type for this client."""
        return "responses"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None
    ) -> str | LLMResponse:
        """Send messages to OpenAI Responses API and return the response.
        
        Args:
            messages: Conversation history with role/content dicts.
            tools: Optional tool definitions for native tool calling.
            tool_choice: How to use tools ("auto", "required", "none", or specific).
        
        Returns:
            LLMResponse with tool_calls if tools were called,
            or str for content-only responses.
        """
        instructions, input_messages = self._split_messages(messages)
        
        # Build request kwargs
        kwargs = {
            "model": self._model,
            "instructions": instructions,
            "input": input_messages,
            "timeout": REQUEST_TIMEOUT_SECONDS,
        }
        
        # Add native tool parameters if provided
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        
        # Responses API is stateful - store=True keeps conversation state
        # so tool results can be submitted back with the response ID
        kwargs["store"] = True
        
        response = self._client.responses.create(**kwargs)
        self._last_response_id = response.id
        return self._parse_response(response)

    def submit_tool_outputs(self, tool_outputs: list[NativeToolOutput]) -> str | LLMResponse:
        """Submit function_call_output items to continue Responses API tool loop."""
        if not self._last_response_id:
            raise ValueError("No previous response id available for tool-output continuation.")

        input_items = [
            {
                "type": "function_call_output",
                "call_id": t.call_id,
                "output": t.output,
            }
            for t in tool_outputs
        ]

        response = self._client.responses.create(
            model=self._model,
            previous_response_id=self._last_response_id,
            input=input_items,
            timeout=REQUEST_TIMEOUT_SECONDS,
            store=True,
        )
        self._last_response_id = response.id
        return self._parse_response(response)

    def _parse_response(self, response) -> str | LLMResponse:
        """Parse Responses API output into unified LLMResponse/string."""
        tool_calls = []
        content_parts = []
        seen_types: list[str] = []
        unknown_types: list[str] = []

        for item in response.output:
            item_type = getattr(item, "type", "<missing>")
            seen_types.append(item_type)

            if item_type == "function_call":
                args = json.loads(item.arguments) if isinstance(item.arguments, str) else (item.arguments or {})
                call_id = getattr(item, "call_id", None) or item.id
                tool_calls.append(NativeToolCall(
                    id=call_id,
                    name=item.name,
                    arguments=args,
                ))
            elif item_type == "message":
                for content in item.content:
                    if hasattr(content, "text") and content.text:
                        content_parts.append(content.text)
            else:
                unknown_types.append(item_type)

        if DEBUG_LOGS and unknown_types:
            print(
                "[debug] RESPONSES PARSE: unknown output item types "
                f"{sorted(set(unknown_types))} "
                f"response_id={getattr(response, 'id', None)}",
                file=sys.stderr,
            )

        if tool_calls:
            return LLMResponse(
                content="\n".join(content_parts) if content_parts else None,
                tool_calls=tool_calls,
            )

        if response.output_text:
            return response.output_text

        if DEBUG_LOGS and getattr(response, "output", None):
            print(
                "[debug] RESPONSES PARSE: empty output_text with non-empty output items "
                f"types={seen_types} response_id={getattr(response, 'id', None)}",
                file=sys.stderr,
            )

        return ""

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

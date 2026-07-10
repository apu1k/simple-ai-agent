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
        self._last_tools: list[dict] | None = None
        self._last_tool_choice: str | dict | None = None

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

    def reset_conversation(self) -> None:
        """Clear stateful Responses API continuation state."""
        self._last_response_id = None
        self._last_tools = None
        self._last_tool_choice = None

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
        
        # Build request kwargs.
        #
        # Responses API is stateful when previous_response_id is supplied.
        # On the first call, send the full local transcript. On later calls,
        # continue the stored response chain and send only the latest message
        # delta. This preserves native tool-call/tool-output context across
        # normal follow-up turns instead of relying on local text replay.
        kwargs = {
            "model": self._model,
            "instructions": instructions,
            "timeout": REQUEST_TIMEOUT_SECONDS,
        }
        if self._last_response_id:
            kwargs["previous_response_id"] = self._last_response_id
            kwargs["input"] = input_messages[-1:] if input_messages else []
        else:
            kwargs["input"] = input_messages
        
        # Cache the latest native-tool configuration so Responses tool-output
        # continuations can resend the same schemas. Responses API calls that use
        # previous_response_id should not rely on provider-side memory of tool schemas.
        self._last_tools = tools
        self._last_tool_choice = tool_choice

        # Add native tool parameters if provided
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        
        # Responses API is stateful - store=True keeps conversation state
        # so tool results can be submitted back with the response ID
        kwargs["store"] = True
        
        self._debug_log_response_request_tools("chat", kwargs)
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

        kwargs = {
            "model": self._model,
            "previous_response_id": self._last_response_id,
            "input": input_items,
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "store": True,
        }

        # Resend the same native-tool configuration used by chat(). This is
        # important for multi-step tool chains such as:
        # search/read -> propose_file_edit.
        if self._last_tools is not None:
            kwargs["tools"] = self._last_tools
        if self._last_tool_choice is not None:
            kwargs["tool_choice"] = self._last_tool_choice

        self._debug_log_response_request_tools("submit_tool_outputs", kwargs)
        response = self._client.responses.create(**kwargs)
        self._last_response_id = response.id
        return self._parse_response(response)

    def _debug_log_response_request_tools(self, label: str, kwargs: dict) -> None:
        """Log the actual tool schemas sent to the Responses API request."""
        if not DEBUG_LOGS:
            return

        tools = kwargs.get("tools") or []
        names = []

        for item in tools:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "function":
                continue

            # Responses schema uses top-level name.
            if isinstance(item.get("name"), str):
                names.append(item["name"])
                continue

            # Chat Completions schema uses nested function.name. Include this
            # defensively so diagnostics are useful if the wrong schema leaks in.
            function = item.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])

        print(
            f"[debug] RESPONSES REQUEST {label}: "
            f"previous_response_id={bool(kwargs.get('previous_response_id'))} "
            f"tool_count={len(tools)} "
            f"tools={names}",
            file=sys.stderr,
        )

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
        """Separate system messages from Responses-compatible input messages."""
        instructions = []
        input_messages = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "") or ""

            if role == "system":
                instructions.append(content)
                continue

            if role in {"user", "assistant"}:
                input_messages.append({"role": role, "content": content})
                continue

            if role == "tool":
                name = msg.get("name", "tool")
                input_messages.append({
                    "role": "user",
                    "content": f"TOOL RESULT ({name}): {content}",
                })

        return "\n\n".join(instructions), input_messages

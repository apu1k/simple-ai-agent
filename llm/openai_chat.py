"""
llm/openai_chat.py

OpenAI chat completions client.
Implements llm/base.py LLMClient protocol.
"""

import json
import sys
import time

from openai import OpenAI

from config.settings import DEBUG_LOGS
from llm.base import LLMResponse, NativeToolCall
from llm.providers import ProviderConfig

REQUEST_TIMEOUT_SECONDS = 180.0

# Keep this small: the Agent owns semantic retries. This retry only smooths over
# transient provider/gateway empty responses.
MAX_EMPTY_RESPONSE_RETRIES = 1
EMPTY_RESPONSE_RETRY_DELAY_SECONDS = 0.25


class OpenAIChatClient:
    """LLM client using the OpenAI chat completions API."""

    def __init__(self, provider: ProviderConfig):
        if provider.base_url:
            self._client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        else:
            self._client = OpenAI(api_key=provider.api_key)
        self._model = provider.default_model
        self._provider_key = provider.key
        self._provider_label = provider.label

    @property
    def supports_native_tools(self) -> bool:
        """Chat Completions API supports native tool calling."""
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
        tool_choice: str | dict | None = None,
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
        kwargs = {
            "model": self._model,
            "messages": messages,
            "timeout": REQUEST_TIMEOUT_SECONDS,
        }

        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        last_result: str | LLMResponse = ""

        for attempt in range(MAX_EMPTY_RESPONSE_RETRIES + 1):
            response = self._client.chat.completions.create(**kwargs)
            result = self._parse_response(response, attempt=attempt)

            if not self._is_empty_result(result):
                return result

            last_result = result

            if attempt < MAX_EMPTY_RESPONSE_RETRIES:
                self._debug_empty_response(
                    reason="empty parsed chat_completions response; retrying once",
                    response=response,
                    attempt=attempt,
                )
                time.sleep(EMPTY_RESPONSE_RETRY_DELAY_SECONDS)

        return last_result

    def _parse_response(self, response, attempt: int = 0) -> str | LLMResponse:
        """Parse Chat Completions output into the unified client return type.

        The method is defensive because OpenAI-compatible gateways may return
        partially valid response objects, such as choices=[], a missing message,
        or a message with neither content nor tool calls.
        """
        choices = getattr(response, "choices", None)
        if not choices:
            self._debug_empty_response(
                reason="chat_completions response has no choices",
                response=response,
                attempt=attempt,
            )
            return ""

        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            self._debug_empty_response(
                reason="chat_completions choice has no message",
                response=response,
                choice=choice,
                attempt=attempt,
            )
            return ""

        raw_tool_calls = getattr(message, "tool_calls", None) or []
        content = getattr(message, "content", None)

        if raw_tool_calls:
            tool_calls: list[NativeToolCall] = []
            for tc in raw_tool_calls:
                function = getattr(tc, "function", None)
                tool_name = getattr(function, "name", None)
                raw_args = getattr(function, "arguments", None)
                tool_call_id = getattr(tc, "id", None)

                if not tool_name:
                    raise ValueError(
                        "Chat Completions tool call is missing function.name "
                        f"tool_call_id={tool_call_id!r}"
                    )

                arguments = self._parse_tool_arguments(
                    raw_args=raw_args,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                )

                tool_calls.append(
                    NativeToolCall(
                        id=tool_call_id,
                        name=tool_name,
                        arguments=arguments,
                    )
                )

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
            )

        if not content:
            self._debug_empty_response(
                reason="chat_completions message has no content and no tool_calls",
                response=response,
                choice=choice,
                message=message,
                attempt=attempt,
            )
            return ""

        return content

    def _parse_tool_arguments(
        self,
        raw_args,
        tool_name: str,
        tool_call_id: str | None,
    ) -> dict:
        """Parse native tool-call arguments defensively.

        OpenAI normally returns function.arguments as a JSON string, but some
        OpenAI-compatible providers may already return a dict.
        """
        if isinstance(raw_args, str):
            stripped = raw_args.strip()
            if not stripped:
                return {}

            try:
                arguments = json.loads(stripped)
            except json.JSONDecodeError as e:
                preview = stripped[:500]
                raise ValueError(
                    f"Invalid JSON arguments for tool '{tool_name}' "
                    f"tool_call_id={tool_call_id!r}: "
                    f"{e.msg} at line {e.lineno}, column {e.colno}. "
                    f"raw={preview!r}"
                ) from e

        elif isinstance(raw_args, dict):
            arguments = raw_args

        elif raw_args is None:
            arguments = {}

        else:
            raise TypeError(
                f"Invalid tool arguments type for tool '{tool_name}' "
                f"tool_call_id={tool_call_id!r}: {type(raw_args).__name__}"
            )

        if not isinstance(arguments, dict):
            raise TypeError(
                f"Tool arguments for tool '{tool_name}' must decode to a JSON object; "
                f"got {type(arguments).__name__} tool_call_id={tool_call_id!r}"
            )

        return arguments

    @staticmethod
    def _is_empty_result(result: str | LLMResponse) -> bool:
        """Return True if a parsed result contains neither non-whitespace text nor tools."""
        if isinstance(result, LLMResponse):
            if result.tool_calls:
                return False
            return not bool((result.content or "").strip())

        return not bool((result or "").strip())

    def _debug_empty_response(
        self,
        reason: str,
        response=None,
        choice=None,
        message=None,
        attempt: int | None = None,
    ) -> None:
        """Emit diagnostics for empty Chat Completions responses."""
        if not DEBUG_LOGS:
            return

        choices = getattr(response, "choices", None)
        choice_count = len(choices) if choices is not None else None

        if choice is None and choices:
            choice = choices[0]

        if message is None and choice is not None:
            message = getattr(choice, "message", None)

        raw_tool_calls = getattr(message, "tool_calls", None) if message is not None else None
        try:
            tool_call_count = len(raw_tool_calls or [])
        except TypeError:
            tool_call_count = "<unknown>"

        content = getattr(message, "content", None) if message is not None else None

        print(
            "[debug] CHAT COMPLETIONS PARSE: empty response | "
            f"reason={reason!r} "
            f"attempt={attempt} "
            f"provider={self._provider_key!r} "
            f"model={self._model!r} "
            f"response_id={getattr(response, 'id', None)!r} "
            f"response_model={getattr(response, 'model', None)!r} "
            f"choices={choice_count} "
            f"finish_reason={getattr(choice, 'finish_reason', None)!r} "
            f"content_present={bool(content)} "
            f"tool_call_count={tool_call_count} "
            f"usage={getattr(response, 'usage', None)!r}",
            file=sys.stderr,
        )

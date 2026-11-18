"""API-key client for Anthropic's native Messages and tool-use protocols."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from anthropic import Anthropic, DefaultHttpxClient

from llm.base import LLMResponse, NativeToolCall, NativeToolOutput

if TYPE_CHECKING:
    from llm.providers import ProviderConfig
    from runtime.state import ModelSettings

_DEFAULT_BASE_URL = "https://api.anthropic.com"
_REQUEST_TIMEOUT = 180.0
_DEFAULT_MAX_TOKENS = 4096
_REASONING_MAX_TOKENS = 32768
# Anthropic recommends starting around 64k at xhigh/max: max_tokens is a hard
# limit on thinking plus reply, and long agentic turns need the headroom.
_HIGH_EFFORT_MAX_TOKENS = 64000
_CACHE_CONTROL = {"type": "ephemeral"}


def _sdk_base_url(base_url: str | None) -> str:
    """The SDK adds /v1/messages or /v1/models, so pass it the service root."""
    parsed = urlsplit(base_url or _DEFAULT_BASE_URL)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.query or parsed.fragment):
        raise ValueError("Anthropic base URL must be HTTPS, without credentials, query, or fragment.")
    path = parsed.path.rstrip("/").removesuffix("/v1/messages").removesuffix("/v1")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def create_anthropic_client(provider: ProviderConfig, **kwargs) -> Anthropic:
    if not provider.api_key:
        raise ValueError("Missing Anthropic API key; configure ANTHROPIC_API_KEY on the backend.")
    return Anthropic(
        api_key=provider.api_key,
        base_url=_sdk_base_url(provider.base_url),
        # Custom x-api-key headers must not follow cross-origin redirects.
        http_client=DefaultHttpxClient(follow_redirects=False),
        **kwargs,
    )


def _message_params(messages: list[dict]) -> tuple[str, list[dict]]:
    """Separate the system prompt and translate legacy OpenAI tool history to text."""
    system: list[str] = []
    converted: list[dict] = []
    for message in messages:
        role, content = message["role"], message.get("content")
        if role == "system":
            if content:
                system.append(content)
            continue
        if role == "tool":
            content = f"TOOL RESULT ({message.get('name') or 'tool'}): {content or ''}"
            role = "user"
        elif role == "assistant" and message.get("tool_calls"):
            calls = [call.get("function", {}) for call in message["tool_calls"]]
            summary = "\n".join(f"- {call.get('name')}({call.get('arguments')})" for call in calls)
            content = f"{content or ''}\n\nNATIVE TOOL CALL REQUEST:\n{summary}".strip()
        elif role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported conversation role for Anthropic: {role!r}")
        if content and (not isinstance(content, str) or content.strip()):
            converted.append({"role": role, "content": content})
    return "\n\n".join(system), converted


def _max_tokens(model: str, effort: str | None) -> int:
    if effort in {"xhigh", "max"}:
        return _HIGH_EFFORT_MAX_TOKENS
    if effort is not None or model.startswith("claude-opus-5-5"):
        return _REASONING_MAX_TOKENS
    return _DEFAULT_MAX_TOKENS


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Mark the newest turn so the next request can reuse the cached prefix.

    Applied to a per-request copy only: stored tool-loop history must not
    accumulate stale breakpoints (Anthropic allows at most four per request).
    """
    if not messages:
        return messages
    *earlier, last = messages
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    blocks[-1] = {**blocks[-1], "cache_control": _CACHE_CONTROL}
    return [*earlier, {**last, "content": blocks}]


def _tool_choice(choice: str | dict) -> dict:
    if isinstance(choice, dict):
        if choice.get("type") == "function":
            return {"type": "tool", "name": choice["function"]["name"]}
        return choice
    return {"type": "any" if choice == "required" else choice}


@dataclass
class _PendingTools:
    options: dict
    messages: list[dict]
    call_ids: tuple[str, ...]


class AnthropicMessagesClient:
    api_type = "anthropic_messages"
    supports_native_tools = True
    supports_native_tool_outputs = True

    def __init__(self, provider: ProviderConfig):
        self._client = create_anthropic_client(provider)
        self._model = provider.default_model
        self._settings: ModelSettings | None = None
        self._pending: _PendingTools | None = None
        self.last_usage = None

    def configure_model_settings(self, settings: ModelSettings | None) -> None:
        self._settings = settings

    def reset_conversation(self) -> None:
        self._pending = None

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> str | LLMResponse:
        self.reset_conversation()
        self.last_usage = None
        system, conversation = _message_params(messages)
        effort = self._settings.anthropic_reasoning_effort if self._settings else None
        options: dict = {
            "model": self._model,
            "timeout": _REQUEST_TIMEOUT,
            "max_tokens": _max_tokens(self._model, effort),
        }
        if system:
            # Breakpoint after tools + system: the stable prefix of every request.
            options["system"] = [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]
        if effort is not None:
            # Anthropic validates model-specific support. Don't turn thinking
            # off, force a thinking mode, or retry with a different effort.
            options["output_config"] = {"effort": effort}
        if tools:
            options["tools"] = tools
            if tool_choice is not None:
                options["tool_choice"] = _tool_choice(tool_choice)
        return self._request(conversation, options)

    def submit_tool_outputs(self, tool_outputs: list[NativeToolOutput]) -> str | LLMResponse:
        pending = self._pending
        if pending is None:
            raise ValueError("There is no pending Anthropic tool request.")
        outputs = {output.call_id: output for output in tool_outputs}
        if len(outputs) != len(tool_outputs) or outputs.keys() != set(pending.call_ids):
            raise ValueError("Anthropic requires exactly one result per pending tool call.")
        blocks = [
            {"type": "tool_result", "tool_use_id": call_id,
             "content": outputs[call_id].output, "is_error": outputs[call_id].is_error}
            for call_id in pending.call_ids
        ]
        return self._request([*pending.messages, {"role": "user", "content": blocks}], pending.options)

    def _request(self, messages: list[dict], options: dict) -> str | LLMResponse:
        self._pending = None
        self.last_usage = None
        # Stream through the SDK to support high-effort, long-running requests.
        # Only the final assembled message is consumed by the agent runtime.
        with self._client.messages.stream(messages=_with_cache_breakpoint(messages), **options) as stream:
            response = stream.get_final_message()
        self.last_usage = response.usage
        if response.stop_reason == "max_tokens":
            raise ValueError("Claude reached its output token limit. Try a lower Anthropic effort or a smaller request.")
        if response.stop_reason == "refusal":
            raise ValueError("Claude declined this request (stop_reason=refusal). Rephrase it or start a new conversation.")
        if response.stop_reason == "model_context_window_exceeded":
            raise ValueError("The conversation exceeds Claude's context window. Reload the context or start a new conversation.")
        if response.stop_reason is None:
            raise ValueError("Anthropic returned an incomplete message stream.")

        text: list[str] = []
        calls: list[NativeToolCall] = []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                if not block.id or not block.name or not isinstance(block.input, dict):
                    raise ValueError("Anthropic returned a malformed tool call.")
                calls.append(NativeToolCall(block.id, block.name, block.input))
        content = "".join(text)
        if calls or response.stop_reason == "tool_use":
            ids = tuple(call.id for call in calls)
            if response.stop_reason != "tool_use" or not ids or len(set(ids)) != len(ids):
                raise ValueError("Anthropic returned an inconsistent tool-use response.")
            # Include all original blocks, in order, including signed/redacted
            # thinking. Keep them in memory only for the active tool loop.
            assistant = {
                "role": "assistant",
                "content": [block.model_dump(mode="json", exclude_unset=True) for block in response.content],
            }
            self._pending = _PendingTools(options, [*messages, assistant], ids)
            return LLMResponse(content or None, calls)
        return content

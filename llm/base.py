"""
llm/base.py

Abstract interface for LLM clients.
Every provider implements this protocol.

To add a new provider:
  1. Create llm/myprovider.py
  2. Implement the LLMClient protocol
  3. Register it in llm/providers.py
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Native tool calling types
# ---------------------------------------------------------------------------

@dataclass
class NativeToolCall:
    """A tool call from a provider's native tool calling API.
    
    Attributes:
        id: Unique identifier for the tool call (provider-specific).
        name: Name of the tool/function to call.
        arguments: Arguments to pass to the tool as a dict.
    """
    id: str
    name: str
    arguments: dict


@dataclass
class NativeToolOutput:
    """A tool output for stateful native tool APIs (e.g., Responses)."""
    call_id: str
    output: str


@dataclass
class LLMResponse:
    """Unified response from an LLM client.
    
    For providers with native tool calling:
      - tool_calls may be populated with NativeToolCall objects
      - content may be None or text
    
    For providers without native tool calling:
      - tool_calls is None
      - content is the response string
    
    Attributes:
        content: Text content from the model (may be None if only tool calls).
        tool_calls: List of native tool calls (may be empty or None).
    """
    content: str | None
    tool_calls: list[NativeToolCall] | None = None


# ---------------------------------------------------------------------------
# LLM Client Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM clients.
    
    Providers may optionally support native tool calling.
    If supports_native_tools returns True, chat() may return
    LLMResponse with tool_calls populated.
    
    For backward compatibility, chat() may also return str
    (treated as content-only response).
    """
    
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None
    ) -> str | LLMResponse:
        """
        Send a list of messages to the LLM and return the reply.
        
        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            tools: Optional tool definitions for native tool calling.
                   Each tool should be in provider-specific format
                   (e.g., OpenAI function format).
            tool_choice: How to use tools. Common values:
                         - "auto": Model decides when to call tools
                         - "required": Model must call a tool
                         - "none": Model must not call tools
                         - dict: Specific tool selection (provider-specific)
        
        Returns:
            Either:
            - A string (content-only response, backward compatible)
            - An LLMResponse (may include tool_calls for native tool calling)
        """
        ...
    
    @property
    def supports_native_tools(self) -> bool:
        """Whether this client supports native tool calling.
        
        Default implementations should return False.
        Providers with native tool support override to return True.
        """
        return False
    
    @property
    def supports_native_tool_outputs(self) -> bool:
        """Whether this client supports structured tool-output continuation."""
        return False

    def submit_tool_outputs(self, tool_outputs: list[NativeToolOutput]) -> str | LLMResponse:
        """Submit native tool outputs to continue a tool loop.

        Clients that do not support this should raise NotImplementedError.
        """
        raise NotImplementedError("This client does not support native tool-output continuation.")

    @property
    def api_type(self) -> str:
        """Return the API type used by this client.
        
        Returns:
            Either "chat_completions" or "responses".
            Default is "chat_completions" for backward compatibility.
        """
        return "chat_completions"

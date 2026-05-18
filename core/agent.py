"""
core/agent.py

The agent loop: takes messages from the user, calls the LLM, dispatches
tool calls, and returns final answers.

Dependencies:
  - core/protocol.py    (parse LLM responses)
  - core/tool_registry.py  (look up and call tools)

No UI, no I/O, no file system access directly.
The IO adapter is injected by runtime/loop.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from core import protocol
from core.tool_registry import registry

if TYPE_CHECKING:
    from llm.base import LLMClient
    from runtime.state import AgentState


# Maximum steps before giving up (prevents infinite loops)
MAX_STEPS = 10
MAX_RETRIES = 2


class Agent:
    def __init__(
        self,
        system_prompt: str,
        state: AgentState,
        llm: LLMClient,
        on_debug: Callable[[str], None] | None = None,
        on_tool: Callable[[str], None] | None = None,
        on_raw: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_display: Callable[[list], None] | None = None,
    ):
        """
        Args:
            system_prompt:  Initial system prompt.
            state:          Agent runtime state (cwd, model config, edit store).
            llm:            LLM client (implements llm.base.LLMClient).
            on_debug:       Optional callback for debug messages.
            on_tool:        Optional callback for tool call log messages.
            on_raw:         Optional callback for raw LLM response strings.
            on_error:       Optional callback for error messages.
            on_display:     Optional callback for display items (file panels, etc).
        """
        self.state = state
        self.llm = llm
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Callbacks — default to no-op so callers don't need to pass them all
        self._debug = on_debug or (lambda msg: None)
        self._tool = on_tool or (lambda msg: None)
        self._raw = on_raw or (lambda msg: None)
        self._error = on_error or (lambda msg: None)
        self._display = on_display or (lambda items: None)

        self._debug(f"SYSTEM PROMPT: {system_prompt}")
        self._debug(
            f"AGENT STATE: cwd={self.state.cwd}, "
            f"provider={self.state.model_config.provider_label}, "
            f"model={self.state.model_config.model}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _runtime_context(self) -> str:
        return (
            "Current local agent runtime state:\n"
            f"- current working directory: {self.state.cwd}\n"
            f"- selected provider: {self.state.model_config.provider_label}\n"
            f"- selected model: {self.state.model_config.model}\n\n"
            "Important:\n"
            "- You are controlling a local agent runtime through tools.\n"
            "- If the user asks where you are in the filesystem, use the current working directory.\n"
            "- If the user asks for the current path, directory, or location, call pwd().\n"
            "- Do not answer such questions as if you were only a remote AI model.\n"
        )

    def _messages_with_context(self) -> list[dict]:
        """Inject a runtime-context system message after the main system prompt."""
        return [
            self.messages[0],
            {"role": "system", "content": self._runtime_context()},
            *self.messages[1:],
        ]

    def _append_tool_result(self, action: str, result: str) -> None:
        self.messages.append({
            "role": "user",
            "content": f"TOOL RESULT ({action}): {result}",
        })

    def _process_tool_result(self, raw_result) -> str:
        """
        Extract a text observation from a tool result.
        If the result carries display items, fire the on_display callback.
        """
        # Import here to avoid a circular dependency at module load time.
        from tools._base import ToolResult

        if isinstance(raw_result, ToolResult):
            if raw_result.display_items:
                self._display(raw_result.display_items)
            return raw_result.observation

        return str(raw_result)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self, user_input: str) -> str:
        """
        Process one user message and return the agent's final reply.

        Runs the tool-call loop until the LLM produces a final answer
        or the step limit is reached.
        """
        self._debug(f"USER INPUT: {user_input}")
        self.messages.append({"role": "user", "content": user_input})

        retry_count = 0

        for _ in range(MAX_STEPS):
            reply = self.llm.chat(self._messages_with_context())

            if not reply:
                self._error("Empty response from LLM")
                return "Error: Empty response from model."

            self._raw(f"RAW MODEL RESPONSE: {reply}")
            parsed = protocol.parse(reply)

            # ---- Invalid response ----------------------------------------
            if not parsed.is_valid:
                self._error(f"Invalid model response: {parsed.error}")

                if retry_count < MAX_RETRIES:
                    self.messages.append({"role": "assistant", "content": reply})
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response was invalid.\n"
                            f"Parser error: {parsed.error}\n\n"
                            "If you intended to call a tool, reply ONLY with one valid "
                            "raw JSON object matching exactly this schema:\n"
                            '{"action": "tool_name", "input": {"param": "value"}}\n\n'
                            "Important:\n"
                            "- Do not explain the tool call.\n"
                            "- Do not put the tool call in Markdown.\n"
                            "- Do not include prose before or after the JSON.\n"
                            "- Always include \"input\", even if it is empty.\n\n"
                            "If you are finished and do not need tools, answer normally."
                        ),
                    })
                    retry_count += 1
                    continue

                self._error("Model failed to produce a valid response after retries.")
                return (
                    "Error: Model failed to return a valid tool call after retries. "
                    f"Last error: {parsed.error}"
                )

            retry_count = 0

            # ---- Tool call -----------------------------------------------
            if parsed.kind == "tool":
                action = parsed.action
                tool_input = parsed.tool_input or {}

                self._debug(f"AVAILABLE TOOLS: {registry.names()}")
                self._debug(f"REQUESTED ACTION: {action}")
                self.messages.append({"role": "assistant", "content": reply})

                if action not in registry:
                    result = (
                        f"Error: Tool '{action}' does not exist. "
                        f"Available tools: {', '.join(registry.names())}"
                    )
                    self._error(result)
                    self._append_tool_result(action, result)
                    continue

                spec = registry.get(action)

                try:
                    if spec.requires_state:
                        raw_result = spec.function(self.state, **tool_input)
                    else:
                        raw_result = spec.function(**tool_input)

                    observation = self._process_tool_result(raw_result)

                except TypeError as e:
                    observation = f"Error: Invalid arguments for tool '{action}': {e}"
                    self._error(observation)
                except Exception as e:
                    observation = f"Error: Tool execution failed for '{action}': {e}"
                    self._error(observation)

                self._tool(f"TOOL CALL: {action}({tool_input}) -> {observation}")
                self._append_tool_result(action, observation)
                continue

            # ---- Final answer --------------------------------------------
            if parsed.kind == "final":
                self.messages.append({"role": "assistant", "content": reply})
                return parsed.final

            return "Error: Unexpected parser state."

        return "Error: Too many agent steps."

    def reset(self, system_prompt: str) -> None:
        """Reset conversation history, keeping the current state."""
        self.messages = [{"role": "system", "content": system_prompt}]

    def update_callbacks(
        self,
        on_debug=None,
        on_tool=None,
        on_raw=None,
        on_error=None,
        on_display=None,
    ) -> None:
        """Replace any subset of callbacks (e.g. when switching IO adapters)."""
        if on_debug is not None:
            self._debug = on_debug
        if on_tool is not None:
            self._tool = on_tool
        if on_raw is not None:
            self._raw = on_raw
        if on_error is not None:
            self._error = on_error
        if on_display is not None:
            self._display = on_display

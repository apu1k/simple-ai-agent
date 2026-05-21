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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from core import protocol
from core.tool_registry import registry

if TYPE_CHECKING:
    from llm.base import LLMClient
    from runtime.state import AgentState
    from core.tool_registry import ToolRegistry


# Maximum steps before giving up (prevents infinite loops)
MAX_STEPS = 10
MAX_RETRIES = 2
MAX_BATCH_TOOL_CALLS = 5
FAIL_FAST_BATCH = True


@dataclass
class BatchToolRecord:
    index: int
    total: int
    action: str
    tool_input: dict
    status: Literal["success", "failed", "skipped"]
    observation: str | None = None
    error: str | None = None
    display_count: int = 0


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
        tool_registry: "ToolRegistry | None" = None,
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
        self.registry = tool_registry or registry
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

    def _append_tool_batch_result(self, result: str) -> None:
        self.messages.append({
            "role": "user",
            "content": f"TOOL RESULT (batch): {result}",
        })

    def _process_tool_result(self, raw_result) -> tuple[str, int]:
        """
        Extract a text observation from a tool result.
        If the result carries display items, fire the on_display callback.
        Returns (observation, display_item_count).
        """
        # Import here to avoid a circular dependency at module load time.
        from tools._base import ToolResult

        if isinstance(raw_result, ToolResult):
            display_count = len(raw_result.display_items or [])
            if raw_result.display_items:
                self._display(raw_result.display_items)
            return raw_result.observation, display_count

        return str(raw_result), 0

    def _execute_one_tool_call(self, action: str, tool_input: dict) -> tuple[str, str, int, str | None]:
        """Execute a single tool call.

        Returns: (status, observation, display_count, error)
        where status is 'success' or 'failed'.
        """
        if action not in self.registry:
            error = (
                f"Error: Tool '{action}' does not exist. "
                f"Available tools: {', '.join(self.registry.names())}"
            )
            self._error(error)
            return "failed", error, 0, error

        spec = self.registry.get(action)

        try:
            if spec.requires_state:
                raw_result = spec.function(self.state, **tool_input)
            else:
                raw_result = spec.function(**tool_input)

            observation, display_count = self._process_tool_result(raw_result)
            return "success", observation, display_count, None

        except TypeError as e:
            observation = f"Error: Invalid arguments for tool '{action}': {e}"
            self._error(observation)
            return "failed", observation, 0, observation
        except Exception as e:
            observation = f"Error: Tool execution failed for '{action}': {e}"
            self._error(observation)
            return "failed", observation, 0, observation

    def _execute_tool_batch(self, calls: list[protocol.ToolCall]) -> list[BatchToolRecord]:
        records: list[BatchToolRecord] = []
        total = len(calls)
        aborted = False

        for i, call in enumerate(calls, start=1):
            if aborted and FAIL_FAST_BATCH:
                records.append(BatchToolRecord(
                    index=i,
                    total=total,
                    action=call.action,
                    tool_input=call.tool_input,
                    status="skipped",
                    observation="Skipped due to earlier failure in fail-fast batch.",
                ))
                continue

            status, observation, display_count, error = self._execute_one_tool_call(
                call.action,
                call.tool_input,
            )
            records.append(BatchToolRecord(
                index=i,
                total=total,
                action=call.action,
                tool_input=call.tool_input,
                status=status,
                observation=observation,
                error=error,
                display_count=display_count,
            ))

            if status == "failed" and FAIL_FAST_BATCH:
                aborted = True

        return records

    def _format_batch_tool_report(self, records: list[BatchToolRecord]) -> str:
        success = sum(1 for r in records if r.status == "success")
        failed = sum(1 for r in records if r.status == "failed")
        skipped = sum(1 for r in records if r.status == "skipped")
        displayed_calls = sum(1 for r in records if r.display_count > 0)
        displayed_items = sum(r.display_count for r in records)

        lines = [f"Tool batch execution report (fail-fast={str(FAIL_FAST_BATCH).lower()}):"]

        for r in records:
            header = f"[{r.index}/{r.total}] {r.action}({r.tool_input})"
            if r.status == "success":
                lines.append(f"- {header} -> success")
                if r.observation:
                    lines.append(f"  observation: {r.observation}")
                if r.display_count > 0:
                    lines.append(f"  display: showed to user ({r.display_count} item(s))")
            elif r.status == "failed":
                lines.append(f"- {header} -> FAILED")
                if r.error:
                    lines.append(f"  error: {r.error}")
                elif r.observation:
                    lines.append(f"  observation: {r.observation}")
            else:
                lines.append(f"- {header} -> SKIPPED")
                if r.observation:
                    lines.append(f"  reason: {r.observation}")

        lines.append(
            "Summary: "
            f"success={success} failed={failed} skipped={skipped} total={len(records)} "
            f"displayed_calls={displayed_calls} displayed_items={displayed_items}"
        )
        return "\n".join(lines)

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
                            "raw JSON object in one of these two shapes:\n"
                            "1) Single tool call with action+input\n"
                            "2) Batch tool calls with tool_calls\n\n"
                            "Important:\n"
                            "- Do not explain the tool call.\n"
                            "- Do not put the tool call in Markdown.\n"
                            "- Do not include prose before or after the JSON.\n"
                            "- Use either a single-call root object or a batch root object.\n"
                            "- In single-call mode, always include \"input\" (even if empty).\n"
                            "- In batch mode, each entry must include \"action\" and \"input\".\n\n"
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
                self._debug(f"AVAILABLE TOOLS: {self.registry.names()}")
                self.messages.append({"role": "assistant", "content": reply})

                calls = parsed.tool_calls
                if not calls:
                    self._error("Parser returned tool kind without calls.")
                    self._append_tool_batch_result("Error: No tool calls were provided.")
                    continue

                if len(calls) > MAX_BATCH_TOOL_CALLS:
                    error_text = (
                        "Error: Too many tool calls requested in one response: "
                        f"{len(calls)} > {MAX_BATCH_TOOL_CALLS}."
                    )
                    self._error(error_text)
                    self._append_tool_batch_result(error_text)
                    continue

                records = self._execute_tool_batch(calls)

                for r in records:
                    if r.status == "success":
                        self._tool(
                            f"TOOL CALL [{r.index}/{r.total}]: "
                            f"{r.action}({r.tool_input}) -> {r.observation}"
                        )
                    elif r.status == "failed":
                        self._tool(
                            f"TOOL CALL [{r.index}/{r.total}]: "
                            f"{r.action}({r.tool_input}) -> FAILED: {r.error or r.observation}"
                        )
                    else:
                        self._tool(
                            f"TOOL CALL [{r.index}/{r.total}]: "
                            f"{r.action}({r.tool_input}) -> SKIPPED"
                        )

                # Backward compatibility: keep legacy per-tool TOOL RESULT shape
                # for single-call responses.
                if len(records) == 1:
                    r = records[0]
                    self._append_tool_result(r.action, r.observation or "")
                else:
                    report = self._format_batch_tool_report(records)
                    self._append_tool_batch_result(report)
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

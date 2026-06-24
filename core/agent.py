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

import json

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from config import MAX_AGENT_STEPS, MAX_BATCH_TOOL_CALLS
from core import protocol
from core.tool_registry import registry
from llm.base import LLMResponse, NativeToolOutput

if TYPE_CHECKING:
    from llm.base import LLMClient
    from runtime.state import AgentState
    from core.tool_registry import ToolRegistry


# Maximum steps before giving up (prevents infinite loops)
MAX_STEPS = MAX_AGENT_STEPS
MAX_RETRIES = 2
MAX_EMPTY_RETRIES = 2
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
        
        # Check if LLM supports native tool calling
        self._use_native_tools = getattr(self.llm, 'supports_native_tools', False)
        self._debug(f"NATIVE TOOLS: {self._use_native_tools}")
        
        # Detect API type for tool format
        self._api_type = getattr(self.llm, 'api_type', 'chat_completions')
        self._debug(f"API TYPE: {self._api_type}")
        self._debug(f"STATE API TYPE: {self.state.model_config.api_type}")
        self._debug(f"STATE PROVIDER KEY: {self.state.model_config.provider_key}")
        self._debug(f"LLM CLIENT CLASS: {self.llm.__class__.__name__}")
        self._debug(f"LLM CLIENT MODULE: {self.llm.__class__.__module__}")

        # Prebuild both tool-schema variants once to avoid runtime shape drift.
        self._tools_by_api_type: dict[str, list[dict]] = {}
        self._pending_native_tool_calls = None
        self._configure_llm_runtime()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _configure_llm_runtime(self) -> None:
        """Refresh llm-dependent runtime caches.

        Must be called whenever self.llm changes (e.g. model/provider switch).
        """
        self._use_native_tools = getattr(self.llm, 'supports_native_tools', False)
        self._api_type = getattr(self.llm, 'api_type', 'chat_completions')
        self._debug(f"NATIVE TOOLS: {self._use_native_tools}")
        self._debug(f"API TYPE: {self._api_type}")
        self._debug(f"STATE API TYPE: {self.state.model_config.api_type}")
        self._debug(f"STATE PROVIDER KEY: {self.state.model_config.provider_key}")
        self._debug(f"LLM CLIENT CLASS: {self.llm.__class__.__name__}")
        self._debug(f"LLM CLIENT MODULE: {self.llm.__class__.__module__}")

        self._tools_by_api_type = {}
        if self._use_native_tools:
            from llm.schema import build_tools_list  # Lazy import
            self._tools_by_api_type = {
                "chat_completions": build_tools_list(self.registry, api_type="chat_completions"),
                "responses": build_tools_list(self.registry, api_type="responses"),
            }
            self._debug(
                "PREBUILT TOOLS: "
                f"chat_completions={len(self._tools_by_api_type['chat_completions'])}, "
                f"responses={len(self._tools_by_api_type['responses'])}"
            )

    def set_llm(self, llm: "LLMClient", system_prompt: str | None = None) -> None:
        """Swap LLM client and refresh all llm-dependent runtime caches.

        If the provider/model switch changes native-tool capability, callers
        should pass a freshly-built system prompt so tool-use instructions stay
        aligned with the active client.
        """
        self.llm = llm
        self._configure_llm_runtime()

        if system_prompt is not None:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = system_prompt
            else:
                self.messages.insert(0, {"role": "system", "content": system_prompt})

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
        """Return messages with runtime context merged into the single leading system message."""
        if not self.messages:
            return [{"role": "system", "content": self._runtime_context()}]

        first = self.messages[0]
        if first.get("role") != "system":
            return [
                {"role": "system", "content": self._runtime_context()},
                *self.messages,
            ]

        base_content = first.get("content", "")
        runtime = self._runtime_context()
        merged_content = f"{base_content}\n\n{runtime}" if base_content else runtime

        return [
            {"role": "system", "content": merged_content},
            *self.messages[1:],
        ]

    def _assert_tools_shape(self, api_type: str, tools: list[dict] | None) -> None:
        """Fail fast when tool payload shape does not match target API."""
        if not tools:
            return

        first = tools[0] if tools else {}
        first_keys = sorted(first.keys()) if isinstance(first, dict) else []

        if api_type == "chat_completions":
            invalid = [
                t for t in tools
                if not (isinstance(t, dict) and t.get("type") == "function" and isinstance(t.get("function"), dict))
            ]
            if invalid:
                raise ValueError(
                    "Tool schema mismatch for chat_completions: expected each tool to contain "
                    "type='function' and nested 'function' object. "
                    f"first_tool_keys={first_keys}"
                )
            return

        if api_type == "responses":
            invalid = [
                t for t in tools
                if not (
                    isinstance(t, dict)
                    and t.get("type") == "function"
                    and isinstance(t.get("name"), str)
                    and "function" not in t
                )
            ]
            if invalid:
                raise ValueError(
                    "Tool schema mismatch for responses: expected each tool to contain "
                    "type='function' and top-level 'name' (without nested 'function'). "
                    f"first_tool_keys={first_keys}"
                )
            return

        raise ValueError(f"Unsupported api_type for tool assertions: {api_type}")

    def _append_tool_result(self, action: str, result: str) -> None:
        self.messages.append({
            "role": "user",
            "content": f"TOOL RESULT ({action}): {result}",
        })

    def _is_effectively_empty(self, parsed: protocol.ParsedResponse, raw_reply: str | None) -> bool:
        """Protocol-aware empty check.

        A response is not empty if:
        - it contains at least one tool call, or
        - it is a final response with non-empty text.
        """
        if parsed.kind == "tool" and bool(parsed.tool_calls):
            return False
        if parsed.kind == "final" and bool(parsed.final):
            return False
        return True

    def _append_tool_batch_result(self, result: str) -> None:
        self.messages.append({
            "role": "user",
            "content": f"TOOL RESULT (batch): {result}",
        })

    def _format_native_tool_call_summary(self, native_tool_calls: list) -> str:
        """Return a local-memory summary of native tool requests.

        Provider-native tool calls are otherwise represented by provider-side
        structured state only. Keeping a compact textual audit record in
        self.messages prevents local conversation memory from losing what the
        agent asked tools to do.
        """
        lines = ["NATIVE TOOL CALL REQUEST:"]
        for tc in native_tool_calls:
            try:
                args = json.dumps(tc.arguments, ensure_ascii=False, sort_keys=True)
            except TypeError:
                args = str(tc.arguments)
            lines.append(f"- id={tc.id} name={tc.name} arguments={args}")
        return "\n".join(lines)

    def _append_tool_records_for_local_memory(self, records: list[BatchToolRecord]) -> None:
        """Append executed tool results to local conversation memory.

        Native-tool APIs may receive these results through structured provider
        protocols, but self.messages is still the agent's local transcript and
        must include tool observations for later turns, debugging, and restore
        paths that replay local history.
        """
        if len(records) == 1:
            r = records[0]
            self._append_tool_result(r.action, r.observation or r.error or "")
        else:
            self._append_tool_batch_result(self._format_batch_tool_report(records))

    def _append_chat_completions_native_tool_call(self, content: str, native_tool_calls: list) -> None:
        """Append native Chat Completions tool calls in OpenAI message format.

        Chat Completions continues tool loops through the message transcript:
        assistant.tool_calls followed by role='tool' messages with matching
        tool_call_id values. A textual summary is not sufficient here.
        """
        tool_calls = []
        for tc in native_tool_calls:
            try:
                args = json.dumps(tc.arguments or {}, ensure_ascii=False, sort_keys=True)
            except TypeError:
                args = json.dumps(str(tc.arguments), ensure_ascii=False)

            tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": args,
                },
            })

        self.messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": tool_calls,
        })

    def _append_chat_completions_tool_results(
        self,
        records: list[BatchToolRecord],
        native_tool_calls: list,
    ) -> None:
        """Append native Chat Completions tool results as role='tool' messages."""
        for r, tc in zip(records, native_tool_calls, strict=False):
            if r.status == "success":
                content = r.observation or ""
            elif r.status == "failed":
                content = r.error or r.observation or "Tool failed."
            else:
                content = r.observation or "Skipped due to earlier failure in fail-fast batch."

            self.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": content,
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
        empty_retry_count = 0
        pending_native_tool_calls = self._pending_native_tool_calls

        for step in range(1, MAX_STEPS + 1):
            if step == MAX_STEPS - 1:
                self.messages.append({
                    "role": "user",
                    "content": (
                        f"IMPORTANT: You are on step {step} out of {MAX_STEPS}. "
                        "You must now produce your final answer. "
                        "Do not call any more tools. Provide a complete response."
                    ),
                })

            # Detect configuration/runtime mismatches early
            if self.state.model_config.api_type != self._api_type:
                err = (
                    "Configuration mismatch: state api_type and llm client api_type differ. "
                    f"state.api_type={self.state.model_config.api_type}, "
                    f"llm.api_type={self._api_type}, "
                    f"provider={self.state.model_config.provider_key}, "
                    f"model={self.state.model_config.model}"
                )
                self._error(err)
                return f"Error: {err}"

            # Select prebuilt tools deterministically by active client API type.
            tools = None
            tool_choice = None
            if self._use_native_tools:
                if self._api_type not in self._tools_by_api_type:
                    err = (
                        "Unsupported llm.api_type for tool selection: "
                        f"{self._api_type}. Available={list(self._tools_by_api_type.keys())}"
                    )
                    self._error(err)
                    return f"Error: {err}"

                tools = self._tools_by_api_type[self._api_type]
                self._assert_tools_shape(self._api_type, tools)
                tool_choice = "auto"

                first_keys = sorted(tools[0].keys()) if tools else []
                self._debug(
                    "TOOL DISPATCH: "
                    f"provider={self.state.model_config.provider_key}, "
                    f"state.api_type={self.state.model_config.api_type}, "
                    f"llm.api_type={self._api_type}, "
                    f"first_tool_keys={first_keys}"
                )
                self._debug(f"TOOLS FORMAT ({self._api_type}): {tools[:1] if tools else []}")
            
            try:
                # For stateful native tool APIs (e.g., Responses), continue with
                # structured function_call_output submission instead of text replay.
                if (
                    pending_native_tool_calls
                    and getattr(self.llm, 'supports_native_tool_outputs', False)
                ):
                    tool_outputs: list[NativeToolOutput] = []
                    for r, tc in pending_native_tool_calls:
                        if r.status == "success":
                            out = r.observation or ""
                        elif r.status == "failed":
                            out = r.error or r.observation or "Tool failed."
                        else:
                            out = r.observation or "Skipped due to earlier failure in fail-fast batch."
                        tool_outputs.append(NativeToolOutput(call_id=tc.id, output=out))

                    reply = self.llm.submit_tool_outputs(tool_outputs)
                    pending_native_tool_calls = None
                    self._pending_native_tool_calls = None
                else:
                    reply = self.llm.chat(
                        self._messages_with_context(),
                        tools=tools,
                        tool_choice=tool_choice
                    )
            except Exception as e:
                err = f"Error: Model request failed: {e}"
                self._error(err)
                return err
            
            # Handle LLMResponse with native tool calls
            parsed: protocol.ParsedResponse
            native_tool_calls = None
            if isinstance(reply, LLMResponse):
                if reply.tool_calls:
                    native_tool_calls = reply.tool_calls

                    normalized_calls: list[protocol.ToolCall] = []
                    for tc in reply.tool_calls:
                        raw_args = tc.arguments

                        if isinstance(raw_args, str):
                            s = raw_args.strip()
                            args = json.loads(s) if s else {}
                        elif isinstance(raw_args, dict):
                            args = raw_args
                        elif raw_args is None:
                            args = {}
                        else:
                            raise TypeError(
                                f"Invalid native tool arguments type for '{tc.name}': "
                                f"{type(raw_args).__name__}"
                            )

                        if not isinstance(args, dict):
                            raise TypeError(
                                f"Native tool arguments for '{tc.name}' must be a JSON object, "
                                f"got {type(args).__name__}"
                            )

                        normalized_calls.append(protocol.ToolCall(tc.name, args))

                    parsed = protocol.ParsedResponse(
                        kind="tool",
                        tool_calls=normalized_calls,
                    )

                    # Use content for logging/raw callback
                    reply = reply.content or ""
                else:
                    # No tool calls - treat content as final
                    reply = reply.content or ""
                    parsed = protocol.parse(reply)
            else:
                # String response - use JSON parser (fallback mode)
                parsed = protocol.parse(reply)
            
            # Check for truly empty response (text-only emptiness is valid when tool calls are present)
            if self._is_effectively_empty(parsed, reply if isinstance(reply, str) else None):
                self._error(
                    "Error: Empty response from LLM | "
                    f"provider={self.state.model_config.provider_key} "
                    f"model={self.state.model_config.model} "
                    f"state.api_type={self.state.model_config.api_type} "
                    f"llm.api_type={self._api_type} "
                    f"parsed.kind={parsed.kind} "
                    f"tool_call_count={len(parsed.tool_calls)} "
                    f"raw_reply_len={len(reply) if isinstance(reply, str) else 0}"
                )

                if empty_retry_count < MAX_EMPTY_RETRIES:
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response was empty. "
                            "Please continue and provide either a valid tool call JSON "
                            "or a final answer."
                        ),
                    })
                    empty_retry_count += 1
                    continue

                return "Error: Empty response from model."

            empty_retry_count = 0
            self._raw(f"RAW MODEL RESPONSE: {reply}")

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
                if native_tool_calls and self._api_type == "chat_completions":
                    self._append_chat_completions_native_tool_call(reply, native_tool_calls)
                elif native_tool_calls and getattr(self.llm, 'supports_native_tool_outputs', False):
                    # Stateful native-tool APIs such as Responses keep the
                    # function-call request in provider state. Do not add a
                    # textual NATIVE TOOL CALL REQUEST summary to local chat
                    # memory; it can pollute future turns and restored chats.
                    pass
                elif native_tool_calls:
                    self.messages.append({
                        "role": "assistant",
                        "content": self._format_native_tool_call_summary(native_tool_calls),
                    })
                else:
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

                # Chat Completions native tools continue through structured
                # assistant.tool_calls + role='tool' transcript messages.
                if native_tool_calls and self._api_type == "chat_completions":
                    self._append_chat_completions_tool_results(records, native_tool_calls)
                    continue

                # For stateful native-tool clients, continue via structured
                # tool outputs (function_call_output). Still record tool results
                # in local memory so later turns and debugging have a complete
                # transcript of what happened.
                if (
                    native_tool_calls
                    and getattr(self.llm, 'supports_native_tool_outputs', False)
                ):
                    # Continue stateful native tool loops through structured
                    # function_call_output submission only. Avoid adding legacy
                    # TOOL RESULT text to local memory for native Responses.
                    pending_native_tool_calls = list(zip(records, native_tool_calls, strict=False))
                    self._pending_native_tool_calls = pending_native_tool_calls
                    continue

                # Backward compatibility: keep legacy per-tool TOOL RESULT shape
                # for non-stateful tool continuation.
                self._append_tool_records_for_local_memory(records)
                continue

            # ---- Final answer --------------------------------------------
            if parsed.kind == "final":
                self._pending_native_tool_calls = None
                self.messages.append({"role": "assistant", "content": reply})
                return parsed.final

            return "Error: Unexpected parser state."

        return "Error: Too many agent steps."

    def reset(self, system_prompt: str) -> None:
        """Reset conversation history, keeping the current state."""
        self.messages = [{"role": "system", "content": system_prompt}]
        self._pending_native_tool_calls = None

        reset_conversation = getattr(self.llm, "reset_conversation", None)
        if callable(reset_conversation):
            reset_conversation()

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

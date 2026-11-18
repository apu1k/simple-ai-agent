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
from typing import TYPE_CHECKING, Callable, Literal, Protocol, cast
from uuid import uuid4

from config import (
    CONTEXT_COMPACTION_ENABLED,
    CONTEXT_COMPACTION_KEEP_RECENT_TURNS,
    CONTEXT_COMPACTION_MIN_RESULT_CHARS,
    CONTEXT_COMPACTION_MIN_SAVINGS_TOKENS,
    CONTEXT_COMPACTION_TRIGGER_TOKENS,
    MAX_AGENT_STEPS,
    MAX_BATCH_TOOL_CALLS,
)
from core import protocol
from core.context_compaction import (
    CONTEXT_COMPACTION_PREFIX,
    INTERNAL_USER_KEY,
    TOOL_RESULT_SUMMARY_KEY,
    CompactionResult,
    CompactionSettings,
    plan_compaction,
    provider_messages,
    tool_result_summary,
    usage_input_tokens,
)
from core.tool_registry import registry
from core.tool_progress import tool_progress_listener
from llm.anthropic_transcript import plain_messages
from llm.base import LLMResponse, NativeToolCall, NativeToolOutput, request_retry_diagnostic
from llm.request_progress import request_progress_listener
from llm.responses_transcript import (
    EXECUTION_REFS_KEY, RESULT_STATUSES_KEY, SEQUENCE_KEY,
    directive_text, entry, execution_output, portable_messages,
)
from night_shifts.models import ToolCallRecord, ToolCallStatus

if TYPE_CHECKING:
    from llm.base import LLMClient
    from runtime.state import AgentState
    from core.tool_registry import ToolRegistry


# Maximum steps before giving up (prevents infinite loops)
MAX_STEPS = MAX_AGENT_STEPS
MAX_RETRIES = 2
MAX_EMPTY_RETRIES = 2
FAIL_FAST_BATCH = True


class _LocalResponsesClient(Protocol):
    replay_scope: str

    def chat_replay(
        self, messages: list[dict], *, tools: list[dict] | None,
        tool_choice: str | dict | None, on_output: Callable[[dict], None],
    ) -> str | LLMResponse: ...


def default_compaction_settings() -> CompactionSettings | None:
    if not CONTEXT_COMPACTION_ENABLED:
        return None
    return CompactionSettings(
        trigger_tokens=CONTEXT_COMPACTION_TRIGGER_TOKENS,
        keep_recent_turns=CONTEXT_COMPACTION_KEEP_RECENT_TURNS,
        min_result_chars=CONTEXT_COMPACTION_MIN_RESULT_CHARS,
        min_savings_tokens=CONTEXT_COMPACTION_MIN_SAVINGS_TOKENS,
    )


@dataclass
class BatchToolRecord:
    index: int
    total: int
    action: str
    tool_input: dict
    status: Literal["success", "failed", "skipped"]
    observation: str | None = None
    error: str | None = None
    execution_id: str | None = None


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
        tool_registry: "ToolRegistry | None" = None,
        agent_profile: str = "head",
        job_id: str | None = None,
        on_execution: Callable[[str, dict], None] | None = None,
        compaction_settings: CompactionSettings | None | Literal["default"] = "default",
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
            compaction_settings: Layer 0 context compaction thresholds;
                            "default" uses config, None disables it.
        """
        self.state = state
        self.llm = llm
        self.registry = tool_registry if tool_registry is not None else registry
        self.agent_profile = agent_profile
        self.job_id = job_id
        self.on_execution = on_execution
        self.on_transcript: Callable[[dict], int] | None = None
        self.on_compaction: Callable[[list[dict]], None] | None = None
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self.compaction_settings: CompactionSettings | None = (
            default_compaction_settings()
            if isinstance(compaction_settings, str)
            else compaction_settings
        )
        # Usage object already acted on; it describes the pre-compaction
        # context and must not trigger another compaction.
        self._compacted_usage: object | None = None
        self._compaction_pending = False

        # Callbacks — default to no-op so callers don't need to pass them all
        self._debug = on_debug or (lambda msg: None)
        self._tool = on_tool or (lambda msg: None)
        self._raw = on_raw or (lambda msg: None)
        self._error = on_error or (lambda msg: None)

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

        # Prebuild tool-schema variants once to avoid runtime shape drift.
        self._tools_by_api_type: dict[str, list[dict]] = {}
        self._pending_native_tool_calls: list[tuple[BatchToolRecord, NativeToolCall]] | None = None
        self._configure_llm_runtime()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _configure_llm_runtime(self) -> None:
        """Refresh llm-dependent runtime caches.

        Must be called whenever self.llm changes (e.g. model/provider switch).
        """
        # Optional client capability: keep live preferences across model switches
        # without imposing OpenAI-specific settings on other LLM clients.
        configure_settings = getattr(self.llm, "configure_model_settings", None)
        if callable(configure_settings):
            configure_settings(getattr(self.state, "model_settings", None))

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
                "anthropic_messages": build_tools_list(self.registry, api_type="anthropic_messages"),
            }
            self._debug("PREBUILT TOOLS: " + ", ".join(
                f"{api}={len(tools)}" for api, tools in self._tools_by_api_type.items()
            ))

    def set_llm(self, llm: "LLMClient", system_prompt: str | None = None) -> None:
        """Swap LLM client and refresh all llm-dependent runtime caches.

        If the provider/model switch changes native-tool capability, callers
        should pass a freshly-built system prompt so tool-use instructions stay
        aligned with the active client.
        """
        self.llm = llm
        self._compaction_pending = False
        self._configure_llm_runtime()

        if system_prompt is not None:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = system_prompt
            else:
                self.messages.insert(0, {"role": "system", "content": system_prompt})

    def _runtime_context(self) -> str:
        include_diff = getattr(
            getattr(self.state, "model_settings", None),
            "include_diff",
            False,
        )
        if include_diff is True:
            diff_setting = "enabled (proposal tools always return diffs)"
        elif include_diff == "model":
            diff_setting = (
                "model choice (request per call with include_diff; defaults to false)"
            )
        else:
            diff_setting = "disabled (proposal tools do not return diffs)"

        return (
            "Current local agent runtime state:\n"
            f"- current working directory: {self.state.cwd}\n"
            f"- selected provider: {self.state.model_config.provider_label}\n"
            f"- selected model: {self.state.model_config.model}\n"
            f"- proposal diff results: {diff_setting}\n"
            f"- elevated requests: {getattr(getattr(self.state, 'privileged_turn', None), 'status', 'disabled')}\n"
            "- Enabling elevation permits requests, not execution: each needs pending acceptance and Windows UAC.\n"
            "- run_shell_command is never elevated. General approved PowerShell execution is capped at 60 seconds.\n"
            "- Fixed evidence/inspection helpers retain installed policy and one-attempt constraints.\n"
            "- Do not re-propose rejected commands, reset claims, repair permissions, or retry unknown outcomes without separate user authorization.\n"
            "- Process completion is not effects verification; timeout is not rollback or proof a VM/service stopped.\n\n"
            "Important:\n"
            "- You are controlling a local agent runtime through tools.\n"
            "- If the user asks where you are in the filesystem, use the current working directory.\n"
            "- If the user asks for the current path, directory, or location, call pwd().\n"
            "- Do not answer such questions as if you were only a remote AI model.\n"
        )

    def _messages_with_context(self) -> list[dict]:
        """Return messages with runtime context merged into the single leading system message."""
        history = portable_messages(provider_messages(self.messages))
        if self._api_type != "anthropic_messages":
            # Claude-native tool blocks can only be replayed to Claude.
            history = plain_messages(history)
        if not history:
            return [{"role": "system", "content": self._runtime_context()}]

        first = history[0]
        if first.get("role") != "system":
            return [
                {"role": "system", "content": self._runtime_context()},
                *history,
            ]

        base_content = first.get("content", "")
        runtime = self._runtime_context()
        merged_content = f"{base_content}\n\n{runtime}" if base_content else runtime

        return [
            {"role": "system", "content": merged_content},
            *history[1:],
        ]

    @property
    def has_provider_managed_context(self) -> bool:
        """A local rewrite cannot change an active provider-side chain."""
        return getattr(self.llm, "has_provider_managed_context", False) is True

    @property
    def uses_local_responses_replay(self) -> bool:
        return self._api_type == "responses" and getattr(self.llm, "uses_local_replay", False) is True

    def _append_message(self, message: dict) -> None:
        if self.uses_local_responses_replay and self.on_transcript is not None:
            sequence = self.on_transcript(message)
            message = {**message, SEQUENCE_KEY: sequence}
        self.messages.append(message)

    def _append_responses_directive(self, scope: str) -> None:
        # Append a state update rather than changing an earlier developer item.
        current = self._runtime_context()
        if directive_text(self.messages, scope) != current:
            self._append_message({**entry("directive", scope, current), INTERNAL_USER_KEY: True})

    def compact_context(self, *, force: bool = False) -> CompactionResult | None:
        """Layer 0: mask old tool output when the context has grown large.

        Must only run between turns, never inside a tool loop. Message
        structure is preserved; only large old tool-result bodies change.
        force=True is the manual command: it ignores the size thresholds and
        also works when automatic compaction is disabled.
        """
        if self.has_provider_managed_context:
            return None
        settings = self.compaction_settings
        if settings is None:
            if not force:
                return None
            settings = default_compaction_settings() or CompactionSettings()
        usage = getattr(self.llm, "last_usage", None)
        reported = None
        if usage is not None and usage is not self._compacted_usage:
            reported = usage_input_tokens(usage)
        result = plan_compaction(self.messages, settings, reported, force=force)
        if result is None:
            return None
        if self.on_compaction is not None:
            self.on_compaction(result.messages)
        # Mutate in place: callers may hold a reference to this list.
        self.messages[:] = result.messages
        self._compacted_usage = usage
        self._compaction_pending = True
        self._tool(
            f"{CONTEXT_COMPACTION_PREFIX}elided "
            f"{result.masked_count} old tool result(s), ~{result.saved_tokens:,} tokens freed "
            f"(local context now ~{result.context_tokens:,} tokens)."
        )
        return result

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

        if api_type == "anthropic_messages":
            if any(not isinstance(t.get("name"), str) or not isinstance(t.get("input_schema"), dict)
                   for t in tools):
                raise ValueError("Anthropic tools must have a name and an input_schema object.")
            return

        raise ValueError(f"Unsupported api_type for tool assertions: {api_type}")

    def _append_tool_result(self, record: BatchToolRecord) -> None:
        self._append_message({
            "role": "user",
            "content": f"TOOL RESULT ({record.action}): {record.observation or record.error or ''}",
            TOOL_RESULT_SUMMARY_KEY: "TOOL RESULT: " + tool_result_summary(
                record.action, record.tool_input, record.status,
            ),
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

    def _append_tool_batch_result(self, result: str, records: list[BatchToolRecord] | None = None) -> None:
        summary = "TOOL RESULT (batch):"
        if records:
            summary += "\n" + "\n".join(
                tool_result_summary(record.action, record.tool_input, record.status) for record in records
            )
        self._append_message({
            "role": "user",
            "content": f"TOOL RESULT (batch): {result}",
            TOOL_RESULT_SUMMARY_KEY: summary,
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

    @staticmethod
    def _native_tool_outputs(pairs: list[tuple[BatchToolRecord, NativeToolCall]]) -> list[NativeToolOutput]:
        outputs: list[NativeToolOutput] = []
        for r, tc in pairs:
            out = execution_output(r.status, r.observation, r.error)
            outputs.append(NativeToolOutput(call_id=tc.id, output=out, is_error=r.status != "success"))
        return outputs

    def _append_tool_records_for_local_memory(self, records: list[BatchToolRecord]) -> None:
        """Append executed tool results to local conversation memory.

        Native-tool APIs may receive these results through structured provider
        protocols, but self.messages is still the agent's local transcript and
        must include tool observations for later turns, debugging, and restore
        paths that replay local history.
        """
        if len(records) == 1:
            self._append_tool_result(records[0])
        else:
            self._append_tool_batch_result(self._format_batch_tool_report(records), records)

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
                TOOL_RESULT_SUMMARY_KEY: tool_result_summary(r.action, r.tool_input, r.status),
            })

    def _start_tool_audit(self, action: str, tool_input: dict) -> str | None:
        """Start a best-effort operational audit record without affecting execution."""
        store = getattr(self.state, "tool_call_store", None)
        if store is None:
            return None
        try:
            return store.start(ToolCallRecord(
                tool_name=action,
                arguments=tool_input,
                agent_profile=self.agent_profile,
                job_id=self.job_id,
                session_id=getattr(self.state, "chat_session_id", None),
            ))
        except Exception as exc:
            self._debug(f"TOOL AUDIT START FAILED: {exc}")
            return None

    def _complete_tool_audit(
        self,
        call_id: str | None,
        status: ToolCallStatus,
        result: str | None,
        error: str | None,
    ) -> None:
        if call_id is None:
            return
        store = getattr(self.state, "tool_call_store", None)
        if store is None:
            return
        try:
            store.complete(call_id, status=status, result=result, error=error)
        except Exception as exc:
            self._debug(f"TOOL AUDIT COMPLETION FAILED: {exc}")

    def _execute_one_tool_call(
        self, action: str, tool_input: dict, *, identity: str | None = None,
    ) -> tuple[Literal["success", "failed"], str, str | None]:
        identity = identity or uuid4().hex
        record = {"id": identity, "tool": action, "arguments": tool_input}
        if self.on_execution is not None:
            # Unlike the best-effort audit, a failed durable intent aborts dispatch.
            self.on_execution("tool_started", dict(record, status="running"))
        result = self._execute_one_tool_call_impl(action, tool_input)
        if self.on_execution is not None:
            status, observation, error = result
            self.on_execution("tool_finished", dict(
                record, status=status, observation=observation, error=error,
            ))
        return result

    def _execute_one_tool_call_impl(self, action: str, tool_input: dict) -> tuple[Literal["success", "failed"], str, str | None]:
        """Execute one tool call and return status, observation, and error."""
        audit_id = self._start_tool_audit(action, tool_input)
        if action not in self.registry:
            error = (
                f"Error: Tool '{action}' does not exist. "
                f"Available tools: {', '.join(self.registry.names())}"
            )
            self._error(error)
            self._complete_tool_audit(audit_id, ToolCallStatus.FAILED, error, error)
            return "failed", error, error

        spec = self.registry.get(action)

        try:
            with tool_progress_listener(self._tool):
                if spec.requires_state:
                    raw_result = spec.function(self.state, **tool_input)
                else:
                    raw_result = spec.function(**tool_input)

            observation = str(raw_result)
            self._complete_tool_audit(audit_id, ToolCallStatus.SUCCESS, observation, None)
            return "success", observation, None

        except TypeError as e:
            observation = f"Error: Invalid arguments for tool '{action}': {e}"
            self._error(observation)
            self._complete_tool_audit(audit_id, ToolCallStatus.FAILED, observation, observation)
            return "failed", observation, observation
        except Exception as e:
            observation = f"Error: Tool execution failed for '{action}': {e}"
            self._error(observation)
            self._complete_tool_audit(audit_id, ToolCallStatus.FAILED, observation, observation)
            return "failed", observation, observation

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

            identity = uuid4().hex if self.uses_local_responses_replay and self.on_execution is not None else None
            if identity is None:
                status, observation, error = self._execute_one_tool_call(call.action, call.tool_input)
            else:
                status, observation, error = self._execute_one_tool_call(
                    call.action, call.tool_input, identity=identity,
                )
            records.append(BatchToolRecord(
                index=i,
                total=total,
                action=call.action,
                tool_input=call.tool_input,
                status=status,
                observation=observation,
                error=error,
                execution_id=identity,
            ))

            if status == "failed" and FAIL_FAST_BATCH:
                aborted = True

        return records

    def _format_batch_tool_report(self, records: list[BatchToolRecord]) -> str:
        success = sum(1 for r in records if r.status == "success")
        failed = sum(1 for r in records if r.status == "failed")
        skipped = sum(1 for r in records if r.status == "skipped")
        lines = [f"Tool batch execution report (fail-fast={str(FAIL_FAST_BATCH).lower()}):"]

        for r in records:
            header = f"[{r.index}/{r.total}] {r.action}({r.tool_input})"
            if r.status == "success":
                lines.append(f"- {header} -> success")
                if r.observation:
                    lines.append(f"  observation: {r.observation}")
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
            f"success={success} failed={failed} skipped={skipped} total={len(records)}"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self, user_input: str) -> str:
        """Consume next-turn authority and revoke it on every exit path."""
        gate = getattr(self.state, "privileged_turn", None)
        boundary = len(self.messages) if self.uses_local_responses_replay else None
        completed = False
        try:
            if gate is None:
                reply = self._step(user_input)
            else:
                with gate.turn(self.agent_profile):
                    reply = self._step(user_input)
            completed = not reply.startswith("Error:")
            return reply
        finally:
            if boundary is not None and not completed:
                # Keep staged SQLite evidence, but do not replay a partial turn.
                del self.messages[boundary:]

    def _step(self, user_input: str) -> str:
        """
        Process one user message and return the agent's final reply.

        Runs the tool-call loop until the LLM produces a final answer
        or the step limit is reached.
        """
        self._debug(f"USER INPUT: {user_input}")
        try:
            self.compact_context()
        except Exception as e:  # Compaction must never block a turn.
            self._error(f"Context compaction failed and was skipped: {e}")
        responses_client = cast(_LocalResponsesClient, self.llm) if self.uses_local_responses_replay else None
        local_responses = responses_client is not None
        if responses_client is not None:
            self._append_responses_directive(responses_client.replay_scope)
        self._append_message({"role": "user", "content": user_input})

        retry_count = 0
        empty_retry_count = 0
        pending_native_tool_calls = self._pending_native_tool_calls

        for step in range(1, MAX_STEPS + 1):
            if step == MAX_STEPS - 1:
                self._append_message({
                    "role": "user",
                    INTERNAL_USER_KEY: True,
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
                if responses_client is not None:
                    self._append_responses_directive(responses_client.replay_scope)
                    with request_progress_listener(self._tool):
                        reply = responses_client.chat_replay(
                            plain_messages(provider_messages(self.messages)), tools=tools,
                            tool_choice=tool_choice, on_output=self._append_message,
                        )
                elif (
                    pending_native_tool_calls
                    and getattr(self.llm, 'supports_native_tool_outputs', False)
                ):
                    tool_outputs = self._native_tool_outputs(pending_native_tool_calls)

                    with request_progress_listener(self._tool):
                        reply = self.llm.submit_tool_outputs(tool_outputs)
                    pending_native_tool_calls = None
                    self._pending_native_tool_calls = None
                else:
                    with request_progress_listener(self._tool):
                        reply = self.llm.chat(
                            self._messages_with_context(),
                            tools=tools,
                            tool_choice=tool_choice
                        )
            except Exception as e:
                status = getattr(e, "status_code", None)
                if local_responses and type(status) is int:
                    # Provider error bodies may echo part of replayed input.
                    parameter = getattr(e, "param", None)
                    field = f" ({parameter})" if isinstance(parameter, str) and parameter in {
                        "service_tier", "tools", "model", "reasoning", "input", "include",
                    } else ""
                    err = f"Error: OpenAI Responses request failed (HTTP {status}){field}."
                else:
                    err = f"Error: Model request failed: {e}"
                diagnostic = request_retry_diagnostic(e)
                if diagnostic is not None:
                    err += "\n" + diagnostic
                self._error(err)
                return err
            
            log_usage = getattr(self.llm, "log_request_usage", None)
            if callable(log_usage):
                log_usage(compacted=self._compaction_pending)
            self._compaction_pending = False

            # Handle LLMResponse with native tool calls
            parsed: protocol.ParsedResponse
            native_tool_calls = None
            native_transcript = False
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
                    if self._use_native_tools:
                        retry_instruction = (
                            "Your previous response was empty. "
                            "Return exactly one of the following:\n"
                            "1. A non-empty final answer, or\n"
                            "2. A valid native tool call.\n\n"
                            "Do not return an empty message."
                        )
                    else:
                        retry_instruction = (
                            "Your previous response was empty. "
                            "Return exactly one of the following:\n"
                            "1. A non-empty final answer, or\n"
                            "2. Exactly one valid raw JSON tool call like "
                            '{"action": "tool_name", "input": {...}}.\n\n'
                            "Do not wrap JSON in Markdown. "
                            "Do not return an empty message."
                        )

                    self._append_message({
                        "role": "user",
                        "content": retry_instruction,
                        INTERNAL_USER_KEY: True,
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
                    if not local_responses:
                        self._append_message({"role": "assistant", "content": reply})
                    self._append_message({
                        "role": "user",
                        INTERNAL_USER_KEY: True,
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
                if local_responses:
                    pass  # chat_replay already recorded the exact output items.
                elif native_tool_calls and self._api_type == "chat_completions":
                    self._append_chat_completions_native_tool_call(reply, native_tool_calls)
                elif native_tool_calls and self._api_type == "anthropic_messages":
                    # Store the provider's exact blocks, including signed
                    # thinking: the next user turn must resend an identical
                    # prefix to read Claude's prompt cache instead of rewriting it.
                    transcript = getattr(self.llm, "transcript_tool_call_message", None)
                    if callable(transcript):
                        self.messages.append(transcript())
                        native_transcript = True
                    else:
                        summary = self._format_native_tool_call_summary(native_tool_calls)
                        self.messages.append({
                            "role": "assistant", "content": f"{reply}\n\n{summary}".strip(),
                        })
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
                elif parsed.consumed_tool_call_markup:
                    # Textual <tool_call>...</tool_call> markup was consumed by
                    # core.protocol. Append only the visible assistant text,
                    # never the raw markup.
                    if parsed.assistant_text.strip():
                        self.messages.append({
                            "role": "assistant",
                            "content": parsed.assistant_text.strip(),
                        })
                else:
                    self.messages.append({"role": "assistant", "content": reply})

                calls = parsed.tool_calls
                if not calls:
                    self._error("Parser returned tool kind without calls.")
                    self._append_tool_batch_result("Error: No tool calls were provided.")
                    continue

                excess_calls: list[protocol.ToolCall] = []
                requested_call_count = len(calls)
                if requested_call_count > MAX_BATCH_TOOL_CALLS:
                    excess_calls = calls[MAX_BATCH_TOOL_CALLS:]
                    calls = calls[:MAX_BATCH_TOOL_CALLS]
                    self._error(
                        "Tool call batch limit exceeded: "
                        f"executing {len(calls)} and skipping {len(excess_calls)} excess call(s)."
                    )

                records = self._execute_tool_batch(calls)

                if excess_calls:
                    for record in records:
                        record.total = requested_call_count
                    records.extend(
                        BatchToolRecord(
                            index=i,
                            total=requested_call_count,
                            action=call.action,
                            tool_input=call.tool_input,
                            status="skipped",
                            observation=(
                                "Skipped: tool call batch limit exceeded. "
                                f"This was call {i} of {requested_call_count}; "
                                f"at most {MAX_BATCH_TOOL_CALLS} calls are executed per batch. "
                                "Retry this call in a new batch and do not assume it ran."
                            ),
                        )
                        for i, call in enumerate(
                            excess_calls,
                            start=MAX_BATCH_TOOL_CALLS + 1,
                        )
                    )

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

                if responses_client is not None and native_tool_calls:
                    outputs = self._native_tool_outputs(list(zip(records, native_tool_calls, strict=True)))
                    message = entry("results", responses_client.replay_scope, [
                        {"type": "function_call_output", "call_id": output.call_id, "output": output.output}
                        for output in outputs
                    ])
                    message[EXECUTION_REFS_KEY] = [record.execution_id for record in records]
                    message[RESULT_STATUSES_KEY] = {
                        output.call_id: record.status for output, record in zip(outputs, records, strict=True)
                    }
                    self._append_message(message)
                    continue

                # Legacy stateful clients still use function_call_output submission.
                if (
                    native_tool_calls
                    and getattr(self.llm, 'supports_native_tool_outputs', False)
                ):
                    # Continue stateful native tool loops through structured
                    # function_call_output submission only. Avoid adding legacy
                    # TOOL RESULT text to local memory for native Responses.
                    pending_native_tool_calls = list(zip(records, native_tool_calls, strict=False))
                    if self._api_type == "anthropic_messages":
                        # Later turns replay these results from local history;
                        # never carry a failed continuation into a new turn.
                        if native_transcript:
                            self.messages.append(self.llm.transcript_tool_result_message(
                                self._native_tool_outputs(pending_native_tool_calls)))
                        else:
                            self._append_tool_records_for_local_memory(records)
                    else:
                        self._pending_native_tool_calls = pending_native_tool_calls
                    continue

                # Backward compatibility: keep legacy per-tool TOOL RESULT shape
                # for non-stateful tool continuation.
                self._append_tool_records_for_local_memory(records)
                continue

            # ---- Final answer --------------------------------------------
            if parsed.kind == "final":
                self._pending_native_tool_calls = None
                if not local_responses:
                    self._append_message({"role": "assistant", "content": reply})
                return parsed.final

            return "Error: Unexpected parser state."

        return "Error: Too many agent steps."

    def reset(self, system_prompt: str) -> None:
        """Reset conversation history and discard any unused privilege grant."""
        gate = getattr(self.state, "privileged_turn", None)
        if gate is not None:
            gate.revoke()
        self.messages = [{"role": "system", "content": system_prompt}]
        self._pending_native_tool_calls = None
        self._compacted_usage = None
        self._compaction_pending = False

        reset_conversation = getattr(self.llm, "reset_conversation", None)
        if callable(reset_conversation):
            reset_conversation()

    def update_callbacks(
        self,
        on_debug=None,
        on_tool=None,
        on_raw=None,
        on_error=None,
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

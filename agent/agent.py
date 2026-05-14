from agent.state import AgentState
from llm.client import chat
from tools import TOOLS
from tools.results import ToolResult
from utils.parser import parse_model_response
from utils.logger import debug, tool, raw, error
from utils.ui import show_display_items


class Agent:
    def __init__(self, system_prompt, state: AgentState):
        self.state = state
        self.messages = [{"role": "system", "content": system_prompt}]

        debug(f"SYSTEM PROMPT: {system_prompt}")
        debug(
            f"AGENT STATE: cwd={self.state.cwd}, "
            f"provider={self.state.model_config.provider_label}, "
            f"model={self.state.model_config.model}, "
            f"api_type={self.state.model_config.api_type}"
        )

    def _runtime_context(self):
        return (
            "Current local agent runtime state:\n"
            f"- current working directory: {self.state.cwd}\n"
            f"- selected provider: {self.state.model_config.provider_label}\n"
            f"- selected model: {self.state.model_config.model}\n\n"
            "Important:\n"
            "- You are controlling a local agent runtime through tools.\n"
            "- If the user asks where you are in the filesystem, use the current working directory.\n"
            "- If the user asks for the current path, directory, location, or agent state, call the pwd tool or answer using this runtime state.\n"
            "- Do not answer such questions as if you were only a remote AI model without local state.\n"
        )

    def _messages_with_runtime_context(self):
        return [
            self.messages[0],
            {"role": "system", "content": self._runtime_context()},
            *self.messages[1:],
        ]

    def _append_tool_observation(self, action, tool_result):
        self.messages.append({
            "role": "user",
            "content": f"TOOL RESULT ({action}): {tool_result}",
        })

    def _process_tool_result(self, tool_result):
        if isinstance(tool_result, ToolResult):
            if tool_result.display_items:
                show_display_items(tool_result.display_items)

            return tool_result.observation

        return str(tool_result)

    def step(self, user_input):
        debug(f"USER INPUT: {user_input}")

        self.messages.append({"role": "user", "content": user_input})
        invalid_tool_call_retry_count = 0

        for _ in range(10):
            reply = chat(self._messages_with_runtime_context(), self.state.model_config)

            if not reply:
                error("Empty response from model")
                return "Error: Empty response from model"

            raw(f"RAW MODEL RESPONSE: {reply}")

            parsed = parse_model_response(reply)

            if not parsed.is_valid:
                error(f"Invalid model response: {parsed.error}")

                if invalid_tool_call_retry_count < 2:
                    self.messages.append({"role": "assistant", "content": reply})
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response was invalid.\n"
                            f"Parser error: {parsed.error}\n\n"
                            "If you intended to call a tool, reply ONLY with one valid raw JSON object "
                            "matching exactly this schema:\n"
                            '{"action": "tool_name", "input": {"param": "value"}}\n\n'
                            "Important:\n"
                            "- Do not explain the tool call.\n"
                            "- Do not introduce the tool call.\n"
                            "- Do not say what tool you would call.\n"
                            "- Do not put the tool call in Markdown.\n"
                            "- Do not put the tool call in a code fence.\n"
                            "- Do not include prose before or after the JSON.\n"
                            "- Do not include extra keys.\n"
                            "- Always include \"input\", even if it is empty.\n\n"
                            "If you are finished and do not need tools, answer normally in plain text."
                        ),
                    })

                    invalid_tool_call_retry_count += 1
                    continue

                error("Model failed to return a valid tool call after retries")
                return (
                    "Error: Model failed to return a valid tool call after retries. "
                    f"Last parser error: {parsed.error}"
                )

            invalid_tool_call_retry_count = 0

            if parsed.kind == "tool":
                action = parsed.action
                tool_input = parsed.tool_input or {}

                debug(f"AVAILABLE TOOLS: {list(TOOLS.keys())}")
                debug(f"REQUESTED ACTION: {action}")

                self.messages.append({"role": "assistant", "content": reply})

                if action not in TOOLS:
                    tool_result = (
                        f"Error: Tool '{action}' does not exist. "
                        f"Available tools: {', '.join(TOOLS.keys())}"
                    )
                    error(tool_result)
                    self._append_tool_observation(action, tool_result)
                    continue

                tool_spec = TOOLS[action]
                tool_function = tool_spec["function"]
                requires_state = tool_spec.get("requires_state", False)

                try:
                    if requires_state:
                        raw_tool_result = tool_function(self.state, **tool_input)
                    else:
                        raw_tool_result = tool_function(**tool_input)

                    tool_observation = self._process_tool_result(raw_tool_result)

                except TypeError as e:
                    tool_observation = f"Error: Invalid arguments for tool '{action}': {e}"
                    error(tool_observation)
                except Exception as e:
                    tool_observation = f"Error: Tool execution failed for tool '{action}': {e}"
                    error(tool_observation)

                tool(f"TOOL CALL: {action}({tool_input}) -> {tool_observation}")
                self._append_tool_observation(action, tool_observation)
                continue

            if parsed.kind == "final":
                final_answer = parsed.final
                self.messages.append({"role": "assistant", "content": reply})
                return final_answer

            return "Error: Unexpected parser state."

        return "Error: Too many agent steps"

    def reset(self, system_prompt):
        self.messages = [{"role": "system", "content": system_prompt}]
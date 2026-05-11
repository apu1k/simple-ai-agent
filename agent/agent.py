from agent.state import AgentState
from llm.client import chat
from tools import TOOLS
from utils.parser import parse_action
from utils.logger import debug, tool, raw, error


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

    def step(self, user_input):
        debug(f"USER INPUT: {user_input}")
        self.messages.append({"role": "user", "content": user_input})

        retry_count = 0

        for _ in range(10):
            reply = chat(self._messages_with_runtime_context(), self.state.model_config)

            if not reply:
                error("Empty response from model")
                return "Error: Empty response from model"

            raw(f"RAW MODEL RESPONSE: {reply}")

            action, result = parse_action(reply)

            if action is None and result is None:
                if retry_count < 2:
                    error("Invalid JSON from model, retrying...")
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response was not valid JSON or did not match the required schema. "
                            "Reply ONLY with valid JSON in one of these formats: "
                            '{"action": "tool_name", "input": {"param": "value"}} '
                            'or {"final": "your answer"}.'
                        )
                    })
                    retry_count += 1
                    continue

                error("Model failed to return valid JSON after retries")
                return reply

            debug(f"AVAILABLE TOOLS: {list(TOOLS.keys())}")
            debug(f"REQUESTED ACTION: {action}")

            if action:
                if action not in TOOLS:
                    error(f"Tool '{action}' not found")
                    return f"Error: Tool '{action}' does not exist."

                if not isinstance(result, dict):
                    error("Tool input is not a dictionary")
                    return "Error: Invalid tool input. Expected a JSON object."

                tool_spec = TOOLS[action]
                tool_function = tool_spec["function"]
                requires_state = tool_spec.get("requires_state", False)

                try:
                    if requires_state:
                        tool_result = tool_function(self.state, **result)
                    else:
                        tool_result = tool_function(**result)
                except TypeError as e:
                    error(f"Tool argument error: {e}")
                    return f"Error: Invalid arguments for tool '{action}': {e}"
                except Exception as e:
                    error(f"Tool execution error: {e}")
                    return f"Error: Tool execution failed: {e}"

                tool(f"TOOL CALL: {action}({result}) -> {tool_result}")

                self.messages.append({"role": "assistant", "content": reply})
                self.messages.append({
                    "role": "user",
                    "content": f"TOOL RESULT: {tool_result}"
                })

                continue

            if result is not None:
                if isinstance(result, str) and result.startswith("FINAL:"):
                    result = result.replace("FINAL:", "", 1).strip()
                return str(result)

            return reply

        return "Error: Too many agent steps"

    def reset(self, system_prompt):
        self.messages = [{"role": "system", "content": system_prompt}]
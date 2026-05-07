from llm.client import chat
from tools import TOOLS
from utils.parser import parse_action
from utils.logger import debug, tool, raw, error


class Agent:
    def __init__(self, system_prompt, model):
        self.model = model
        self.messages = [{"role": "system", "content": system_prompt}]
        debug(f"SYSTEM PROMPT: {system_prompt}")

    def step(self, user_input):
        debug(f"USER INPUT: {user_input}")
        self.messages.append({"role": "user", "content": user_input})

        retry_count = 0

        for _ in range(10):
            response = chat(self.messages, self.model)
            reply = response.choices[0].message.content

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

                try:
                    tool_result = TOOLS[action](**result)
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
from llm.client import chat
from config import MODEL
from tools import TOOLS
from utils.parser import parse_action
from utils.logger import debug, tool, raw, error

class Agent:
    def __init__(self, system_prompt):
        self.messages = [{"role": "system", "content": system_prompt}]
        print("DEBUG SYSTEM PROMPT:", system_prompt)

    def step(self, user_input):
        debug(f"USER INPUT: {user_input}")
        self.messages.append({"role": "user", "content": user_input})

        retry_count = 0
        for _ in range(10):
            response = chat(self.messages, MODEL)
            reply = response.choices[0].message.content
            if not reply:
                error("Empty response from model")
                return "Error: Empty response from model"
            
            raw(f"RAW: {reply}")

            action, result = parse_action(reply)

            if action is None and result is None:
                if retry_count < 2:
                    error("Invalid JSON from model, retrying...")

                    self.messages.append({
                        "role": "user",
                        "content": "Deine letzte Antwort war kein gültiges JSON. Antworte NUR mit gültigem JSON."
                    })

                    retry_count += 1
                    continue
                else:
                    error("Model failed twice, using raw output")
                    return reply

            debug(f"AVAILABLE TOOLS: {list(TOOLS.keys())}")
            debug(f"REQUESTED ACTION: {action}")

            # ✅ Tool Call
            if action:
                if action not in TOOLS:
                    error(f"[ERROR] Tool '{action}' nicht gefunden")
                    return f"Tool '{action}' existiert nicht."

                if not isinstance(result, dict):
                    error("Tool input is not a dict")
                    return "Error: Invalid tool input"

                try:
                    # ❌ Schutz vor verschachtelten Tool Calls
                    if not isinstance(result, dict):
                        error("Tool input is not a dict")
                        return "Error: Invalid tool input"

                    if any(isinstance(v, dict) for v in result.values()):
                        error("Nested tool call detected")
                        return "Error: Nested tool calls are not allowed"

                    # ✅ Tool ausführen
                    try:
                        tool_result = TOOLS[action](**result)
                    except Exception as e:
                        error(f"Tool Error: {e}")
                        return f"Tool execution failed: {e}"
                except Exception as e:
                    error(f"Tool Error: {e}")
                    return f"Tool execution failed: {e}"

                tool(f"[TOOL] {action} -> {tool_result}")

                self.messages.append({"role": "assistant", "content": reply})
                self.messages.append({
                    "role": "user",
                    "content": f"TOOL RESULT: {tool_result}"
                })

                continue  # ✅ jetzt erlaubt

            # ✅ Final Answer
            if result:
                if isinstance(result, str) and result.startswith("FINAL:"):
                    result = result.replace("FINAL:", "").strip()
                return result

            # fallback
            return reply
        return "Error: Too many steps"

    def reset(self, system_prompt):
        self.messages = [{"role": "system", "content": system_prompt}]

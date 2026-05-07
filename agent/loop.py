from agent.agent import Agent
from agent.prompt import build_system_prompt
from config import MODEL
from utils.logger import ai


def run_agent():
    agent = Agent(build_system_prompt(), MODEL)

    while True:
        user_input = input("You: ")
        cmd = user_input.strip().lower()

        if cmd.startswith("\\"):
            if cmd == "\\reset":
                agent = Agent(build_system_prompt(), MODEL)
                ai("AI: Context has been reset.")
            elif cmd in ["\\exit", "\\quit"]:
                ai("AI: Goodbye.")
                break
            else:
                ai("AI: Unknown command.")
            continue

        reply = agent.step(user_input)
        ai("AI: " + reply)
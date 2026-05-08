from pathlib import Path

from agent.agent import Agent
from agent.prompt import build_system_prompt
from agent.state import AgentState
from config import MODEL
from utils.logger import ai


def run_agent():
    state = AgentState(
        cwd=Path.cwd(),
        model=MODEL
    )

    agent = Agent(build_system_prompt(), state)

    while True:
        user_input = input("You: ")
        cmd = user_input.strip().lower()

        if cmd.startswith("\\"):
            if cmd == "\\reset":
                agent = Agent(build_system_prompt(), state)
                ai("AI: Context has been reset.")
            elif cmd in ["\\exit", "\\quit"]:
                ai("AI: Goodbye.")
                break
            else:
                ai("AI: Unknown command.")
            continue

        reply = agent.step(user_input)
        ai("AI: " + reply)
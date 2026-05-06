from agent.agent import Agent
from agent.prompt import build_system_prompt
from utils.logger import user, ai

def run_agent():
    agent = Agent(build_system_prompt())

    while True:
        user_input = input("Du: ")
        cmd = user_input.strip().lower()

        # ✅ Commands
        if cmd.startswith("\\"):
            if cmd == "\\reset":
                agent = Agent(build_system_prompt())
                ai("AI: Kontext zurückgesetzt.")
            elif cmd in ["\\exit", "\\quit"]:
                ai("AI: Beenden.")
                break
            else:
                ai("AI: Unbekannter Befehl")
            continue

        # ✅ Agent arbeitet
        reply = agent.step(user_input)
        ai("AI: " + reply)
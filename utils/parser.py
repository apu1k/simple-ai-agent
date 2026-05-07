import json
import re


def extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def parse_action(text):
    try:
        clean_text = extract_json(text)
        data = json.loads(clean_text)

        if not isinstance(data, dict):
            print("PARSE ERROR: JSON root must be an object")
            print("RAW TEXT:", text)
            return None, None

        if "action" in data:
            action = data["action"]
            tool_input = data.get("input", {})

            if tool_input is None:
                tool_input = {}

            return action, tool_input

        if "final" in data:
            return None, data["final"]

        print("PARSE ERROR: JSON must contain either 'action' or 'final'")
        print("RAW TEXT:", text)

    except Exception as e:
        print("PARSE ERROR:", e)
        print("RAW TEXT:", text)

    return None, None
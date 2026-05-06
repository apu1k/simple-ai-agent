import json
import re

def extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text

def parse_action(text):
    try:
        clean_text = extract_json(text)
        data = json.loads(clean_text)

        if "action" in data:
            return data["action"], data["input"]

        if "final" in data:
            return None, data["final"]

    except Exception as e:
        print("PARSE ERROR:", e)
        print("RAW TEXT:", text)

    return None, None
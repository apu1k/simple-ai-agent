from openai import OpenAI
from config import API_KEY, API_BASE

client = OpenAI(
    api_key=API_KEY,
    base_url=API_BASE
)

def chat(messages, model):
    return client.chat.completions.create(
        model=model,
        messages=messages
    )
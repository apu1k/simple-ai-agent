from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE = os.getenv("OPENAI_BASE_URL")

MODEL = "gwdg.qwen3-30b-a3b-instruct-2507"
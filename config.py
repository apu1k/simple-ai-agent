import os
from dotenv import load_dotenv


load_dotenv()

# GWDG / current default provider
GWDG_API_KEY = os.getenv("GWDG_API_KEY") or os.getenv("OPENAI_API_KEY")
GWDG_BASE_URL = os.getenv("GWDG_BASE_URL") or os.getenv("OPENAI_BASE_URL")
GWDG_DEFAULT_MODEL = os.getenv("GWDG_DEFAULT_MODEL", "gwdg.qwen3-30b-a3b-instruct-2507")

# UPB AI Gateway
UPB_API_KEY = os.getenv("UPB_API_KEY") or GWDG_API_KEY
UPB_BASE_URL = os.getenv("UPB_BASE_URL", "https://ai-gateway.uni-paderborn.de/v1")
UPB_DEFAULT_MODEL = os.getenv("UPB_DEFAULT_MODEL", "")

# Personal OpenAI account
OPENAI_PERSONAL_API_KEY = os.getenv("OPENAI_PERSONAL_API_KEY")
OPENAI_PERSONAL_DEFAULT_MODEL = os.getenv("OPENAI_PERSONAL_DEFAULT_MODEL", "gpt-4.1-mini")
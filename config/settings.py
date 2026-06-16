"""
config/settings.py

App-level paths and environment loading.
No imports from this project.
"""

from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)

PROVIDERS_FILE = PROJECT_ROOT / "providers.toml"
PROVIDERS_EXAMPLE_FILE = PROJECT_ROOT / "providers.example.toml"

# Agent operational limits
MAX_AGENT_STEPS = 10
MAX_BATCH_TOOL_CALLS = 10

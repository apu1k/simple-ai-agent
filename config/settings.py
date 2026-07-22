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
OPERATIONAL_DATA_DIR = PROJECT_ROOT / ".agent_runtime"
OPERATIONAL_DATABASE = OPERATIONAL_DATA_DIR / "operations.sqlite3"

# Agent operational limits
MAX_AGENT_STEPS = 10
MAX_BATCH_TOOL_CALLS = 10

# Debug logging controls
# Toggle to True for verbose bootstrap diagnostics.
DEBUG_LOGS = False

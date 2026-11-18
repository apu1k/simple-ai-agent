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
RUNTIME_DATABASE = OPERATIONAL_DATA_DIR / "runtime.sqlite3"

# Agent operational limits
MAX_AGENT_STEPS = 32
MAX_BATCH_TOOL_CALLS = 16

# Layer 0 context compaction: mask old tool output between turns.
# See core/context_compaction.py. Set CONTEXT_COMPACTION_ENABLED = False to disable.
CONTEXT_COMPACTION_ENABLED = True
CONTEXT_COMPACTION_TRIGGER_TOKENS = 100_000
CONTEXT_COMPACTION_KEEP_RECENT_TURNS = 3
CONTEXT_COMPACTION_MIN_RESULT_CHARS = 1_000
CONTEXT_COMPACTION_MIN_SAVINGS_TOKENS = 20_000

# Debug logging controls
# Toggle to True for verbose bootstrap diagnostics.
DEBUG_LOGS = False

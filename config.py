from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)

PROVIDERS_FILE = PROJECT_ROOT / "providers.toml"
PROVIDERS_EXAMPLE_FILE = PROJECT_ROOT / "providers.example.toml"
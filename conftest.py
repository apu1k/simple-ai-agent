"""
conftest.py

Ensures the project root is on sys.path so that all packages
(core, tools, editing, llm, io, runtime, config) are importable
during pytest runs without needing `pip install -e .`.
"""

import sys
from pathlib import Path

# Project root = the directory containing this file
PROJECT_ROOT = Path(__file__).parent.resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

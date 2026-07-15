"""
conftest.py

Ensures the project root is on sys.path so that all packages
(core, tools, editing, llm, io, runtime, config) are importable
during pytest runs without needing `pip install -e .`.
"""

import os
import sys
from pathlib import Path

# Tests must not inherit Textual Serve's development environment. Otherwise
# importing Textual connects pytest to devtools and recreates textual.log.
os.environ.pop("TEXTUAL", None)
os.environ.pop("TEXTUAL_LOG", None)

# Project root = the directory containing this file
PROJECT_ROOT = Path(__file__).parent.resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

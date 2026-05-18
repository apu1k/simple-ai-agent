"""
tests/tools/fs/test_analyze.py

Tests for tools/fs/analyze.py: analyze_python_file, analyze_python_files.
"""

from dataclasses import dataclass, field
from pathlib import Path

from editing.store import EditStore
from tools.fs.analyze import analyze_python_file, analyze_python_files


@dataclass
class FakeState:
    cwd: Path
    edit_store: EditStore = field(default_factory=EditStore)


def make_state(tmp_path):
    return FakeState(cwd=tmp_path)


EXAMPLE_SOURCE = "\n".join([
    '"""Example module."""',
    "import os",
    "from pathlib import Path",
    "",
    "CONSTANT = 123",
    "",
    "class Example(Base):",
    "    class_value = 456",
    "",
    "    async def run(self, value: int = 1) -> str:",
    "        hidden_detail = 'must not be exposed'",
    "        return str(value)",
    "",
    "def helper(name):",
    "    hidden_body = 'also not exposed'",
    "    return name",
    "",
])


def test_analyze_python_file_structure(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "example.py").write_text(EXAMPLE_SOURCE, encoding="utf-8")

    result = analyze_python_file(state, "example.py")

    assert "File: example.py" in result
    assert "Module docstring:" in result
    assert "present" in result
    assert "import os" in result
    assert "from pathlib import Path" in result
    assert "CONSTANT" in result
    assert "helper(name)" in result
    assert "Example" in result
    assert "Bases: Base" in result
    assert "class_value" in result
    assert "async run(self, value: int=1) -> str" in result


def test_analyze_python_file_hides_bodies(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "example.py").write_text(EXAMPLE_SOURCE, encoding="utf-8")

    result = analyze_python_file(state, "example.py")

    assert "hidden_detail" not in result
    assert "hidden_body" not in result
    assert "return str(value)" not in result
    assert "return name" not in result


def test_analyze_python_file_syntax_error(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    result = analyze_python_file(state, "broken.py")

    assert "Syntax error:" in result
    assert "line" in result


def test_analyze_python_file_non_python(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "example.txt").write_text("hello", encoding="utf-8")

    result = analyze_python_file(state, "example.txt")

    assert result.startswith("Error:")
    assert "not a Python file" in result


def test_analyze_python_files_multiple(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "a.py").write_text(
        "VALUE_A = 1\n\ndef alpha():\n    return VALUE_A\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text(
        "VALUE_B = 2\n\nclass Beta:\n    def run(self):\n        return VALUE_B\n",
        encoding="utf-8",
    )

    result = analyze_python_files(state, "*.py", path=".", max_files=30)

    assert "Analyzed 2 Python file(s)" in result
    assert "VALUE_A" in result
    assert "alpha()" in result
    assert "VALUE_B" in result
    assert "Beta" in result
    assert "run(self)" in result
    assert "return VALUE_A" not in result
    assert "return VALUE_B" not in result


def test_analyze_python_files_skips_ignored(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "visible.py").write_text("def visible():\n    pass\n", encoding="utf-8")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "hidden.py").write_text("def hidden():\n    pass\n", encoding="utf-8")

    result = analyze_python_files(state, "*.py", path=".", max_files=30)

    assert "visible.py" in result
    assert "hidden.py" not in result


def test_analyze_python_files_respects_max(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b(): pass\n", encoding="utf-8")

    result = analyze_python_files(state, "*.py", path=".", max_files=1)

    assert "Analyzed 1 Python file(s)" in result
    assert "Result limit reached" in result

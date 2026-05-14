from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.file_tools import (
    cd,
    find_files,
    ls,
    pwd,
    read_file,
    resolve_path,
    search_text,
    show_file,
    show_files,
)
from tools.results import ToolResult


@dataclass
class FakeState:
    cwd: Path


def make_state(tmp_path):
    return FakeState(cwd=tmp_path)


def test_resolve_path_resolves_relative_path_against_state_cwd(tmp_path):
    state = make_state(tmp_path)

    resolved = resolve_path(state, "subdir/file.txt")

    assert resolved == (tmp_path / "subdir" / "file.txt").resolve()


def test_resolve_path_keeps_absolute_path(tmp_path):
    state = make_state(tmp_path)
    absolute_path = (tmp_path / "file.txt").resolve()

    resolved = resolve_path(state, absolute_path)

    assert resolved == absolute_path


def test_pwd_returns_current_working_directory(tmp_path):
    state = make_state(tmp_path)

    result = pwd(state)

    assert result == str(tmp_path)


def test_ls_lists_files_and_directories(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "dir_a").mkdir()
    (tmp_path / "file_b.txt").write_text("hello", encoding="utf-8")

    result = ls(state, ".")

    assert "Directory:" in result
    assert "Entries: 2" in result
    assert 'name="dir_a"' in result
    assert 'name="file_b.txt"' in result
    assert "[DIR]" in result
    assert "[FILE]" in result


def test_ls_returns_error_for_missing_path(tmp_path):
    state = make_state(tmp_path)

    result = ls(state, "does-not-exist")

    assert result.startswith("Error:")
    assert "Path does not exist" in result


def test_cd_changes_current_working_directory(tmp_path):
    state = make_state(tmp_path)
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    result = cd(state, "target")

    assert result == f"Changed directory to: {target_dir.resolve()}"
    assert state.cwd == target_dir.resolve()


def test_cd_returns_error_for_file_path(tmp_path):
    state = make_state(tmp_path)
    file_path = tmp_path / "file.txt"
    file_path.write_text("hello", encoding="utf-8")

    result = cd(state, "file.txt")

    assert result.startswith("Error:")
    assert "Path is not a directory" in result
    assert state.cwd == tmp_path


def test_read_file_reads_utf8_text_file(tmp_path):
    state = make_state(tmp_path)
    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello world", encoding="utf-8")

    result = read_file(state, "hello.txt")

    assert result == "hello world"


def test_read_file_returns_error_for_missing_file(tmp_path):
    state = make_state(tmp_path)

    result = read_file(state, "missing.txt")

    assert result.startswith("Error:")
    assert "File does not exist" in result


def test_read_file_returns_error_for_directory(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "some_dir").mkdir()

    result = read_file(state, "some_dir")

    assert result.startswith("Error:")
    assert "Path is not a file" in result


def test_read_file_returns_error_for_too_large_file(tmp_path, monkeypatch):
    import tools.file_tools as file_tools

    state = make_state(tmp_path)
    file_path = tmp_path / "large.txt"
    file_path.write_text("1234567890", encoding="utf-8")

    monkeypatch.setattr(file_tools, "MAX_FILE_SIZE_BYTES", 5)

    result = read_file(state, "large.txt")

    assert result.startswith("Error:")
    assert "File is too large to read" in result


def test_show_file_complete_file_returns_tool_result_with_display_item(tmp_path):
    state = make_state(tmp_path)
    file_path = tmp_path / "example.py"
    file_content = "print('secret content')\nprint('second line')\n"
    file_path.write_text(file_content, encoding="utf-8")

    result = show_file(state, "example.py")

    assert isinstance(result, ToolResult)
    assert len(result.display_items) == 1

    display_item = result.display_items[0]

    assert display_item.kind == "file"
    assert display_item.display_path == "example.py"
    assert display_item.title == "File: example.py Complete"
    assert display_item.content == file_content
    assert display_item.language == "python"
    assert display_item.start_line == 1
    assert display_item.end_line == 2
    assert display_item.complete is True

    assert "Displayed file" in result.observation
    assert "example.py" in result.observation

    # Critical rule:
    # The file content is shown to the user via display_items,
    # but must not be returned to the model in observation.
    assert "secret content" in display_item.content
    assert "secret content" not in result.observation


def test_show_file_line_range_returns_only_requested_lines(tmp_path):
    state = make_state(tmp_path)
    file_path = tmp_path / "example.py"
    file_path.write_text(
        "line 1\nline 2 secret\nline 3 selected\nline 4\n",
        encoding="utf-8",
    )

    result = show_file(state, "example.py", start_line=2, end_line=3)

    assert isinstance(result, ToolResult)
    assert len(result.display_items) == 1

    display_item = result.display_items[0]

    assert display_item.title == "File: example.py Lines: 2-3"
    assert display_item.content == "line 2 secret\nline 3 selected\n"
    assert display_item.start_line == 2
    assert display_item.end_line == 3
    assert display_item.complete is False

    assert "line 2 secret" in display_item.content
    assert "line 2 secret" not in result.observation
    assert "lines 2-3" in result.observation


@pytest.mark.parametrize(
    "start_line,end_line,expected_message",
    [
        (0, 2, "start_line must be greater than or equal to 1"),
        (5, 2, "end_line must be greater than or equal to start_line"),
        ("abc", 2, "start_line must be an integer"),
        (1, "abc", "end_line must be an integer"),
    ],
)
def test_show_file_returns_error_for_invalid_line_ranges(
    tmp_path,
    start_line,
    end_line,
    expected_message,
):
    state = make_state(tmp_path)
    file_path = tmp_path / "example.py"
    file_path.write_text("line 1\nline 2\n", encoding="utf-8")

    result = show_file(
        state,
        "example.py",
        start_line=start_line,
        end_line=end_line,
    )

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert expected_message in result


def test_show_file_returns_error_when_complete_file_is_too_large(tmp_path, monkeypatch):
    import tools.file_tools as file_tools

    state = make_state(tmp_path)
    file_path = tmp_path / "large.py"
    file_path.write_text("print('too large')\n", encoding="utf-8")

    monkeypatch.setattr(file_tools, "MAX_DISPLAY_FILE_SIZE_BYTES", 5)

    result = show_file(state, "large.py")

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "File is too large to display completely" in result
    assert "Request a line range instead" in result


def test_find_files_finds_matching_files_and_skips_ignored_dirs(tmp_path):
    state = make_state(tmp_path)

    (tmp_path / "keep.py").write_text("print('keep')", encoding="utf-8")

    ignored_dir = tmp_path / "__pycache__"
    ignored_dir.mkdir()
    (ignored_dir / "ignored.py").write_text("print('ignored')", encoding="utf-8")

    result = find_files(state, "*.py", path=".", max_results=100)

    assert "Found 1 file(s)" in result
    assert "keep.py" in result
    assert "ignored.py" not in result


def test_search_text_finds_text_matches(tmp_path):
    state = make_state(tmp_path)
    file_path = tmp_path / "example.py"
    file_path.write_text(
        "alpha\nneedle here\nomega\n",
        encoding="utf-8",
    )

    result = search_text(state, "needle", path=".", file_pattern="*.py")

    assert "Found 1 text match(es)" in result
    assert "example.py:2: needle here" in result


def test_search_text_skips_ignored_dirs(tmp_path):
    state = make_state(tmp_path)

    ignored_dir = tmp_path / ".venv"
    ignored_dir.mkdir()
    (ignored_dir / "ignored.py").write_text("needle", encoding="utf-8")

    result = search_text(state, "needle", path=".", file_pattern="*.py")

    assert "No text matches found" in result
    assert "ignored.py" not in result


def test_show_files_returns_tool_result_with_multiple_display_items(tmp_path):
    state = make_state(tmp_path)

    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"

    file_a.write_text("print('secret a')\n", encoding="utf-8")
    file_b.write_text("print('secret b')\n", encoding="utf-8")

    result = show_files(state, "*.py", path=".", max_files=30)

    assert isinstance(result, ToolResult)
    assert len(result.display_items) == 2

    displayed_paths = {item.display_path for item in result.display_items}
    displayed_contents = [item.content for item in result.display_items]

    assert displayed_paths == {"a.py", "b.py"}
    assert "print('secret a')\n" in displayed_contents
    assert "print('secret b')\n" in displayed_contents

    assert "Displayed 2 file(s)" in result.observation
    assert "a.py" in result.observation
    assert "b.py" in result.observation

    # Critical rule:
    # File names may appear in the observation,
    # but file contents must not.
    assert "secret a" not in result.observation
    assert "secret b" not in result.observation


def test_show_files_respects_max_files(tmp_path):
    state = make_state(tmp_path)

    (tmp_path / "a.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("print('b')\n", encoding="utf-8")

    result = show_files(state, "*.py", path=".", max_files=1)

    assert isinstance(result, ToolResult)
    assert len(result.display_items) == 1
    assert "Result limit reached" in result.observation


def test_show_files_skips_ignored_dirs(tmp_path):
    state = make_state(tmp_path)

    (tmp_path / "visible.py").write_text("print('visible')\n", encoding="utf-8")

    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    (ignored_dir / "hidden.py").write_text("print('hidden')\n", encoding="utf-8")

    result = show_files(state, "*.py", path=".", max_files=30)

    assert isinstance(result, ToolResult)
    assert len(result.display_items) == 1
    assert result.display_items[0].display_path == "visible.py"
    assert "visible.py" in result.observation
    assert "hidden.py" not in result.observation
    assert "hidden" not in result.observation
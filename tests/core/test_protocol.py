"""
tests/core/test_protocol.py

Tests for core/protocol.py (the LLM response parser).
Migrated from tests/test_parser.py.
"""

import pytest
from core.protocol import MAX_TOOL_CALLS_PER_TURN, parse


# ---------------------------------------------------------------------------
# Valid tool calls
# ---------------------------------------------------------------------------

def test_valid_tool_call_no_params():
    r = parse('{"action": "pwd", "input": {}}')
    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.action == "pwd"
    assert r.tool_input == {}
    assert r.final is None
    assert r.error is None


def test_valid_tool_call_with_params():
    r = parse('{"action": "read_file", "input": {"path": "main.py"}}')
    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.action == "read_file"
    assert r.tool_input == {"path": "main.py"}


def test_valid_tool_call_with_outer_whitespace():
    r = parse('\n  {"action": "pwd", "input": {}}  \n')
    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.action == "pwd"


def test_valid_batch_tool_calls():
    r = parse(
        '{"tool_calls": ['
        '{"action": "pwd", "input": {}}, '
        '{"action": "ls", "input": {"path": "."}}'
        ']}'
    )
    assert r.is_valid is True
    assert r.kind == "tool"
    assert len(r.tool_calls) == 2
    assert r.tool_calls[0].action == "pwd"
    assert r.tool_calls[0].tool_input == {}
    assert r.tool_calls[1].action == "ls"
    assert r.tool_calls[1].tool_input == {"path": "."}

    # Backward-compat properties should still reflect first call
    assert r.action == "pwd"
    assert r.tool_input == {}


def test_invalid_batch_tool_calls_empty():
    r = parse('{"tool_calls": []}')
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert "at least one" in (r.error or "")


def test_invalid_batch_tool_calls_non_list():
    r = parse('{"tool_calls": {"action": "pwd", "input": {}}}')
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert "JSON array" in (r.error or "")


def test_invalid_batch_mixed_root_shapes():
    r = parse(
        '{"tool_calls": [{"action": "pwd", "input": {}}], '
        '"action": "pwd", "input": {}}'
    )
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert "either {'action','input'} or 'tool_calls'" in (r.error or "")


def test_invalid_batch_too_many_tool_calls():
    calls = ", ".join('{"action": "pwd", "input": {}}' for _ in range(MAX_TOOL_CALLS_PER_TURN + 1))
    r = parse('{"tool_calls": [' + calls + ']}')
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert "Too many tool calls" in (r.error or "")


# ---------------------------------------------------------------------------
# Final answers
# ---------------------------------------------------------------------------

def test_plain_text_is_final_answer():
    text = "I displayed the files above."
    r = parse(text)
    assert r.is_valid is True
    assert r.kind == "final"
    assert r.final == text
    assert r.action is None
    assert r.tool_input is None


def test_markdown_text_is_final_answer():
    text = "\nHere is the result:\n\n- Item one\n- Item two\n\n**Done.**\n"
    r = parse(text)
    assert r.is_valid is True
    assert r.kind == "final"
    assert r.final == text


def test_non_tool_json_object_is_final_answer():
    text = '{"name": "Alice", "age": 30}'
    r = parse(text)
    assert r.is_valid is True
    assert r.kind == "final"
    assert r.final == text


def test_legacy_final_json_is_final_answer():
    r = parse('{"final": "Done."}')
    assert r.is_valid is True
    assert r.kind == "final"
    assert r.final == "Done."


# ---------------------------------------------------------------------------
# Embedded tool call in prose → invalid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    'I would call: {"action": "pwd", "input": {}}',
    'Here is the tool call:\n{"action": "pwd", "input": {}}',
    '{"action": "pwd", "input": {}} is what I would use.',
    'To inspect the file, I would use {"action": "read_file", "input": {"path": "main.py"}}.',
])
def test_embedded_tool_call_in_prose_is_invalid(text):
    r = parse(text)
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None
    assert "embedded tool call" in r.error or "attempted tool call" in r.error


# ---------------------------------------------------------------------------
# Markdown-fenced tool call → invalid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    '```json\n{"action": "pwd", "input": {}}\n```',
    '```\n{"action": "pwd", "input": {}}\n```',
])
def test_markdown_fenced_tool_call_is_invalid(text):
    r = parse(text)
    assert r.is_valid is False
    assert r.kind == "invalid"


# ---------------------------------------------------------------------------
# Invalid tool call structures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    '{"action": "pwd"}',                              # missing input
    '{"input": {}}',                                  # missing action
    '{"action": "pwd", "input": {}, "note": "x"}',   # extra key
    '{"action": 123, "input": {}}',                   # action not a string
    '{"action": "   ", "input": {}}',                 # action blank
    '{"action": "pwd", "input": []}',                 # input is array
    '{"action": "pwd", "input": "nope"}',             # input is string
    '{"action": "pwd", "input": null}',               # input is null
])
def test_invalid_tool_call_structures(text):
    r = parse(text)
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None


def test_malformed_json_looks_like_tool_call():
    r = parse('{"action": "pwd", "input": {}')   # truncated
    assert r.is_valid is False
    assert r.kind == "invalid"
    assert "not valid raw JSON" in r.error or "attempted tool call" in r.error


# ---------------------------------------------------------------------------
# Empty / null inputs
# ---------------------------------------------------------------------------

def test_empty_string_is_invalid():
    r = parse("")
    assert r.is_valid is False
    assert r.kind == "invalid"


def test_whitespace_only_is_invalid():
    r = parse("   \n\t   ")
    assert r.is_valid is False
    assert r.kind == "invalid"


def test_none_is_invalid():
    r = parse(None)
    assert r.is_valid is False
    assert r.kind == "invalid"


# ---------------------------------------------------------------------------
# OpenAI/ChatGPT-style textual <tool_call> markup
# ---------------------------------------------------------------------------

def test_textual_tool_call_is_parsed_and_stripped():
    text = """I will read it now.

<tool_call>
{"recipient_name":"functions.read_file","parameters":{"path":"README.md"}}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.consumed_tool_call_markup is True
    assert r.assistant_text == "I will read it now."
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].action == "read_file"
    assert r.tool_calls[0].tool_input == {"path": "README.md"}


def test_textual_tool_call_without_functions_prefix():
    text = """<tool_call>
{"recipient_name":"read_file","parameters":{"path":"README.md"}}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.tool_calls[0].action == "read_file"
    assert r.tool_calls[0].tool_input == {"path": "README.md"}


def test_multiple_textual_tool_calls_are_parsed():
    text = """I will inspect both files.

<tool_call>
{"recipient_name":"functions.read_file","parameters":{"path":"a.py"}}
</tool_call>

<tool_call>
{"recipient_name":"functions.read_file","parameters":{"path":"b.py"}}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.consumed_tool_call_markup is True
    assert r.assistant_text == "I will inspect both files."
    assert len(r.tool_calls) == 2
    assert r.tool_calls[0].action == "read_file"
    assert r.tool_calls[0].tool_input == {"path": "a.py"}
    assert r.tool_calls[1].action == "read_file"
    assert r.tool_calls[1].tool_input == {"path": "b.py"}


def test_textual_tool_call_coerces_stringified_json_parameters():
    text = """<tool_call>
{"recipient_name":"functions.propose_file_edit","parameters":{"path":"x.py","edits":"[]"}}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.tool_calls[0].action == "propose_file_edit"
    assert r.tool_calls[0].tool_input == {
        "path": "x.py",
        "edits": [],
    }


def test_textual_tool_call_accepts_stringified_parameters_object():
    text = """<tool_call>
{"recipient_name":"functions.read_file","parameters":"{\\"path\\": \\"README.md\\"}"}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is True
    assert r.kind == "tool"
    assert r.tool_calls[0].action == "read_file"
    assert r.tool_calls[0].tool_input == {"path": "README.md"}


def test_invalid_textual_tool_call_json_is_invalid():
    text = """<tool_call>
{"recipient_name":"functions.read_file","parameters":{"path":"README.md"}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None
    assert "Invalid <tool_call> JSON" in r.error


def test_textual_tool_call_parameters_must_be_object():
    text = """<tool_call>
{"recipient_name":"functions.read_file","parameters":["README.md"]}
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None
    assert "parameters" in r.error


def test_incomplete_textual_tool_call_is_invalid():
    text = """I will read it now.

<tool_call>
{"recipient_name":"functions.read_file","parameters":{"path":"README.md"}}
"""

    r = parse(text)

    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None
    assert "Incomplete or malformed <tool_call> block" in r.error


def test_orphan_textual_tool_call_closing_tag_is_invalid():
    text = """I am done.
</tool_call>
"""

    r = parse(text)

    assert r.is_valid is False
    assert r.kind == "invalid"
    assert r.error is not None
    assert "Incomplete or malformed <tool_call> block" in r.error

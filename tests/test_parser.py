import pytest

from utils.parser import parse_action, parse_model_response


def test_parse_valid_tool_call_without_input_parameters():
    parsed = parse_model_response('{"action": "pwd", "input": {}}')

    assert parsed.is_valid is True
    assert parsed.kind == "tool"
    assert parsed.action == "pwd"
    assert parsed.tool_input == {}
    assert parsed.final is None
    assert parsed.error is None


def test_parse_valid_tool_call_with_input_parameters():
    parsed = parse_model_response(
        '{"action": "read_file", "input": {"path": "main.py"}}'
    )

    assert parsed.is_valid is True
    assert parsed.kind == "tool"
    assert parsed.action == "read_file"
    assert parsed.tool_input == {"path": "main.py"}


def test_parse_valid_tool_call_with_outer_whitespace():
    parsed = parse_model_response('\n  {"action": "pwd", "input": {}}  \n')

    assert parsed.is_valid is True
    assert parsed.kind == "tool"
    assert parsed.action == "pwd"
    assert parsed.tool_input == {}


def test_parse_plain_text_as_final_answer():
    text = "I displayed the files above."

    parsed = parse_model_response(text)

    assert parsed.is_valid is True
    assert parsed.kind == "final"
    assert parsed.final == text
    assert parsed.action is None
    assert parsed.tool_input is None
    assert parsed.error is None


def test_parse_markdown_text_as_final_answer():
    text = """
Here is the result:

- Item one
- Item two

**Done.**
"""

    parsed = parse_model_response(text)

    assert parsed.is_valid is True
    assert parsed.kind == "final"
    assert parsed.final == text


def test_parse_non_tool_json_object_as_final_answer():
    text = '{"name": "Alice", "age": 30}'

    parsed = parse_model_response(text)

    assert parsed.is_valid is True
    assert parsed.kind == "final"
    assert parsed.final == text


def test_parse_legacy_final_json_as_final_answer():
    parsed = parse_model_response('{"final": "Done."}')

    assert parsed.is_valid is True
    assert parsed.kind == "final"
    assert parsed.final == "Done."


@pytest.mark.parametrize(
    "text",
    [
        'I would call: {"action": "pwd", "input": {}}',
        'Here is the tool call:\n{"action": "pwd", "input": {}}',
        '{"action": "pwd", "input": {}} is what I would use.',
        'To inspect the file, I would use {"action": "read_file", "input": {"path": "main.py"}}.',
    ],
)
def test_rejects_embedded_tool_call_inside_normal_text(text):
    parsed = parse_model_response(text)

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None
    assert (
        "embedded tool call" in parsed.error
        or "attempted tool call" in parsed.error
    )


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"action": "pwd", "input": {}}\n```',
        '```\n{"action": "pwd", "input": {}}\n```',
    ],
)
def test_rejects_markdown_code_fenced_tool_call(text):
    parsed = parse_model_response(text)

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None


@pytest.mark.parametrize(
    "text",
    [
        '{"action": "pwd"}',
        '{"input": {}}',
        '{"action": "pwd", "input": {}, "note": "please"}',
        '{"action": 123, "input": {}}',
        '{"action": "   ", "input": {}}',
        '{"action": "pwd", "input": []}',
        '{"action": "pwd", "input": "nope"}',
        '{"action": "pwd", "input": null}',
    ],
)
def test_rejects_invalid_tool_call_structures(text):
    parsed = parse_model_response(text)

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None


def test_rejects_malformed_raw_tool_call_json():
    text = '{"action": "pwd", "input": {}'

    parsed = parse_model_response(text)

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None
    assert "not valid raw JSON" in parsed.error


def test_rejects_empty_response():
    parsed = parse_model_response("")

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None


def test_rejects_whitespace_only_response():
    parsed = parse_model_response("   \n\t   ")

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None


def test_rejects_non_string_response():
    parsed = parse_model_response(None)

    assert parsed.is_valid is False
    assert parsed.kind == "invalid"
    assert parsed.error is not None


def test_parse_action_backward_compatibility_for_tool_call():
    action, tool_input = parse_action('{"action": "pwd", "input": {}}')

    assert action == "pwd"
    assert tool_input == {}


def test_parse_action_backward_compatibility_for_final_answer():
    action, final_text = parse_action("Done.")

    assert action is None
    assert final_text == "Done."


def test_parse_action_backward_compatibility_for_invalid_response(capsys):
    action, result = parse_action('I would call: {"action": "pwd", "input": {}}')

    captured = capsys.readouterr()

    assert action is None
    assert result is None
    assert "PARSE ERROR:" in captured.out
import json
from types import SimpleNamespace

import pytest

from llm.openai_chat import OpenAIChatClient
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig

def _mk_provider():
    return ProviderConfig(
        key="openai",
        label="OpenAI",
        api_key="test",
        base_url="None",
        api_type="chat_completions",
        default_model="gpt-4o-mini",
        supports_model_listing=False,
    )

def _mk_provider_responses():
    return ProviderConfig(
        key="openai",
        label="OpenAI",
        api_key="test",
        base_url="None",
        api_type="responses",
        default_model="gpt-4o-mini",
        supports_model_listing=False,
    )

def _mk_chat_llm(monkeypatch, tool_args):
    response = _mk_chat_response_with_tool_args(tool_args)
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", _FakeChatClient(response))
    return llm

def _mk_responses_llm(monkeypatch, tool_args):
    response = _mk_responses_response_with_tool_args(tool_args)
    llm = OpenAIResponsesClient(_mk_provider_responses())
    monkeypatch.setattr(llm, "_client", _FakeResponsesClient(response))
    return llm


class _FakeCompletions:
    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeChatClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_FakeCompletions(response))


class _FakeResponsesClient:
    def __init__(self, response):
        self.responses = SimpleNamespace(create=lambda **kwargs: response)


def _mk_chat_response_with_tool_args(tool_args):
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="propose_file_edit", arguments=tool_args),
    )
    message = SimpleNamespace(role="assistant", content=None, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    return SimpleNamespace(choices=[choice])


def _mk_responses_response_with_tool_args(tool_args):
    item = SimpleNamespace(
        type="function_call",
        call_id="call_1",
        name="propose_file_edit",
        arguments=tool_args,
    )
    return SimpleNamespace(
        id="resp_1",
        output=[item],
    )


def _dummy_tools():
    return [{"name": "propose_file_edit", "description": "x", "parameters": {}}]


def _dummy_messages():
    return [{"role": "user", "content": "edit file"}]


def test_openai_chat_parses_json_string_object_arguments(monkeypatch):
    llm = _mk_chat_llm(
        monkeypatch,
        json.dumps({"path": "x.py", "edits": [{"find": "a", "replace": "b"}]}),
    )

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())
    tc = out.tool_calls[0]
    assert tc.name == "propose_file_edit"
    assert tc.arguments["path"] == "x.py"
    assert tc.arguments["edits"][0]["find"] == "a"


def test_openai_chat_accepts_native_dict_arguments(monkeypatch):
    llm = _mk_chat_llm(
        monkeypatch,
        {"path": "x.py", "edits": [{"find": "a", "replace": "b"}]},
    )

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())
    tc = out.tool_calls[0]
    assert tc.arguments["path"] == "x.py"
    assert tc.arguments["edits"][0]["replace"] == "b"


@pytest.mark.parametrize("bad_args", ["{", "not-json", "[1,2,3]"])
def test_openai_chat_handles_invalid_or_non_object_string_arguments(monkeypatch, bad_args):
    llm = _mk_chat_llm(monkeypatch, bad_args)

    with pytest.raises(Exception):
        llm.chat(messages=_dummy_messages(), tools=_dummy_tools())


def test_openai_chat_handles_none_arguments(monkeypatch):
    llm = _mk_chat_llm(monkeypatch, None)
    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())
    assert out.tool_calls[0].arguments == {}


def test_provider_parity_for_native_dict_arguments(monkeypatch):
    tool_args = {"path": "x.py", "edits": [{"find": "a", "replace": "b"}]}

    chat = _mk_chat_llm(monkeypatch, tool_args)
    responses = _mk_responses_llm(monkeypatch, tool_args)

    # Current bug: chat path may fail here while responses path succeeds.
    chat_out = chat.chat(messages=_dummy_messages(), tools=_dummy_tools())
    resp_out = responses.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert chat_out.tool_calls[0].name == resp_out.tool_calls[0].name == "propose_file_edit"
    assert chat_out.tool_calls[0].arguments == resp_out.tool_calls[0].arguments


def _mk_empty_choices_response():
    return SimpleNamespace(choices=[])


def _mk_missing_message_response():
    choice = SimpleNamespace(message=None, finish_reason="stop")
    return SimpleNamespace(id="chatcmpl_1", model="test-model", choices=[choice])


def _mk_empty_message_response(content=None, tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(id="chatcmpl_1", model="test-model", choices=[choice])


class _CountingFakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class _CountingFakeChatClient:
    def __init__(self, responses):
        self._completions = _CountingFakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self._completions)

    @property
    def calls(self):
        return self._completions.calls


def test_openai_chat_empty_choices_returns_empty_string_after_retry(monkeypatch):
    fake = _CountingFakeChatClient([_mk_empty_choices_response()])
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", fake)

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert out == ""
    assert fake.calls == 2


def test_openai_chat_missing_message_returns_empty_string_after_retry(monkeypatch):
    fake = _CountingFakeChatClient([_mk_missing_message_response()])
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", fake)

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert out == ""
    assert fake.calls == 2


def test_openai_chat_empty_content_and_no_tool_calls_returns_empty_string_after_retry(monkeypatch):
    fake = _CountingFakeChatClient([
        _mk_empty_message_response(content=None, tool_calls=None),
    ])
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", fake)

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert out == ""
    assert fake.calls == 2


def test_openai_chat_whitespace_content_retries_then_returns_whitespace(monkeypatch):
    fake = _CountingFakeChatClient([
        _mk_empty_message_response(content="   ", tool_calls=None),
    ])
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", fake)

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert out == "   "
    assert fake.calls == 2


def test_openai_chat_empty_then_success_returns_success(monkeypatch):
    fake = _CountingFakeChatClient([
        _mk_empty_choices_response(),
        _mk_empty_message_response(content="final answer", tool_calls=None),
    ])
    llm = OpenAIChatClient(_mk_provider())
    monkeypatch.setattr(llm, "_client", fake)

    out = llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    assert out == "final answer"
    assert fake.calls == 2


def test_openai_chat_invalid_json_arguments_error_contains_context(monkeypatch):
    llm = _mk_chat_llm(monkeypatch, "{bad json")

    with pytest.raises(ValueError) as exc:
        llm.chat(messages=_dummy_messages(), tools=_dummy_tools())

    msg = str(exc.value)
    assert "Invalid JSON arguments" in msg
    assert "propose_file_edit" in msg
    assert "call_1" in msg

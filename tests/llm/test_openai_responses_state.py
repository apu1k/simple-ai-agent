from types import SimpleNamespace

from llm.base import NativeToolOutput
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig


class _FakeResponsesEndpoint:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id=f"resp_{len(self.calls)}",
            output=[],
            output_text=f"answer_{len(self.calls)}",
        )


class _FakeOpenAIClient:
    def __init__(self):
        self.responses = _FakeResponsesEndpoint()


def _provider():
    return ProviderConfig(
        key="test",
        label="Test",
        api_key="test-key",
        base_url=None,
        api_type="responses",
        default_model="test-model",
        supports_model_listing=False,
    )


def test_responses_chat_continues_with_previous_response_id_after_first_call():
    client = OpenAIResponsesClient(_provider())
    fake_openai = _FakeOpenAIClient()
    client._client = fake_openai

    first = client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
    ])
    second = client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer_1"},
        {"role": "user", "content": "second"},
    ])

    assert first == "answer_1"
    assert second == "answer_2"

    first_kwargs = fake_openai.responses.calls[0]
    second_kwargs = fake_openai.responses.calls[1]

    assert "previous_response_id" not in first_kwargs
    assert first_kwargs["input"] == [{"role": "user", "content": "first"}]
    assert second_kwargs["previous_response_id"] == "resp_1"
    assert second_kwargs["input"] == [{"role": "user", "content": "second"}]
    assert second_kwargs["store"] is True


def test_responses_reset_conversation_clears_previous_response_id():
    client = OpenAIResponsesClient(_provider())
    fake_openai = _FakeOpenAIClient()
    client._client = fake_openai

    client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
    ])
    client.reset_conversation()
    client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "fresh"},
    ])

    second_kwargs = fake_openai.responses.calls[1]
    assert "previous_response_id" not in second_kwargs
    assert second_kwargs["input"] == [{"role": "user", "content": "fresh"}]

def test_responses_submit_tool_outputs_resends_cached_tools_and_tool_choice():
    client = OpenAIResponsesClient(_provider())
    fake_openai = _FakeOpenAIClient()
    client._client = fake_openai

    tools = [
        {
            "type": "function",
            "name": "propose_file_edit",
            "description": "Propose a file edit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        }
    ]

    client.chat(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
        ],
        tools=tools,
        tool_choice="auto",
    )

    client.submit_tool_outputs([
        NativeToolOutput(call_id="call_1", output="tool result")
    ])

    first_kwargs = fake_openai.responses.calls[0]
    second_kwargs = fake_openai.responses.calls[1]

    assert first_kwargs["tools"] == tools
    assert first_kwargs["tool_choice"] == "auto"

    assert second_kwargs["previous_response_id"] == "resp_1"
    assert second_kwargs["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "tool result",
        }
    ]
    assert second_kwargs["tools"] == tools
    assert second_kwargs["tool_choice"] == "auto"
    assert second_kwargs["store"] is True


def test_responses_reset_conversation_clears_cached_tools():
    client = OpenAIResponsesClient(_provider())
    fake_openai = _FakeOpenAIClient()
    client._client = fake_openai

    tools = [
        {
            "type": "function",
            "name": "propose_file_edit",
            "description": "Propose a file edit.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    client.chat(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
        ],
        tools=tools,
        tool_choice="auto",
    )

    client.reset_conversation()

    client.chat([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "fresh"},
    ])

    second_kwargs = fake_openai.responses.calls[1]

    assert "previous_response_id" not in second_kwargs
    assert "tools" not in second_kwargs
    assert "tool_choice" not in second_kwargs
    assert second_kwargs["input"] == [{"role": "user", "content": "fresh"}]

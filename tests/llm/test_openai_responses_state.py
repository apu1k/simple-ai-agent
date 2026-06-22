from types import SimpleNamespace

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

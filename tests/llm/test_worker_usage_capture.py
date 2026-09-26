"""No network: SDK-shaped usage does not silently become zero after retries."""

from types import SimpleNamespace

from llm.openai_chat import OpenAIChatClient
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig


def _provider(api_type: str) -> ProviderConfig:
    return ProviderConfig(
        key="fixture", label="Fixture", api_key="dummy", base_url=None,
        api_type=api_type, default_model="fixture-model", supports_model_listing=False,
    )


class _ChatEndpoint:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return next(self.results)


def _chat_response(content: str, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
        usage=usage,
    )


def test_chat_usage_resets_on_missing_usage_and_marks_retry_unknown():
    client = OpenAIChatClient(_provider("chat_completions"))
    endpoint = _ChatEndpoint([
        _chat_response("answer", {"prompt_tokens": 10, "completion_tokens": 5}),
        _chat_response("answer with no usage"),
        _chat_response("", {"prompt_tokens": 3, "completion_tokens": 1}),
        _chat_response("answer after retry", {"prompt_tokens": 10, "completion_tokens": 5}),
    ])
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=endpoint))
    assert client.chat([{"role": "user", "content": "one"}]) == "answer"
    assert client.last_usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert client.chat([{"role": "user", "content": "two"}]) == "answer with no usage"
    assert client.last_usage is None
    assert client.chat([{"role": "user", "content": "three"}]) == "answer after retry"
    assert endpoint.calls == 4
    assert client.last_usage is None  # The earlier empty attempt may have been billed.


class _ResponsesEndpoint:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            id=f"r{self.calls}", output=[], output_text="answer",
            usage={"input_tokens": self.calls, "output_tokens": 2} if self.calls == 1 else None,
        )


def test_responses_usage_is_per_call_and_per_client():
    client = OpenAIResponsesClient(_provider("responses"))
    endpoint = _ResponsesEndpoint()
    client._client = SimpleNamespace(responses=endpoint)
    assert client.chat([{"role": "user", "content": "first"}]) == "answer"
    assert client.last_usage == {"input_tokens": 1, "output_tokens": 2}
    assert client.chat([{"role": "user", "content": "second"}]) == "answer"
    assert client.last_usage is None
    other = OpenAIResponsesClient(_provider("responses"))
    assert other.last_usage is None

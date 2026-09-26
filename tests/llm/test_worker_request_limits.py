"""SDK-shaped offline checks for the opt-in worker-only generation limits."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from llm.base import NativeToolOutput
from llm.openai_chat import OpenAIChatClient
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from llm.worker_limits import WorkerRequestLimits
from runtime.state import ModelSettings


def _provider(api_type):
    return ProviderConfig(
        key="fixture", label="Fixture", api_key="dummy", base_url="https://api.openai.com/v1",
        api_type=api_type, default_model="fixture-model", supports_model_listing=False,
    )


class FakeEndpoint:
    def __init__(self, response):
        self.calls = []
        self.response = response

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeSDK:
    def __init__(self, endpoint, api_type):
        self.endpoint = endpoint
        self.retries = []
        if api_type == "responses":
            self.responses = endpoint
        else:
            self.chat = SimpleNamespace(completions=endpoint)

    def with_options(self, *, max_retries):
        self.retries.append(max_retries)
        return self


def test_worker_chat_flex_has_zero_sdk_and_empty_response_retries():
    client = OpenAIChatClient(_provider("chat_completions"))
    endpoint = FakeEndpoint(SimpleNamespace(choices=[], usage=None))
    sdk = FakeSDK(endpoint, "chat_completions")
    client._client = sdk
    client.configure_model_settings(ModelSettings(openai_flex=True))
    client.configure_worker_limits(WorkerRequestLimits(123, time.monotonic() + 8))
    assert client.chat([{"role": "user", "content": "fixture"}]) == ""
    assert sdk.retries == [0]
    assert len(endpoint.calls) == 1  # No hidden semantic empty-response retry.
    call = endpoint.calls[0]
    assert call["max_completion_tokens"] == 123
    assert call["service_tier"] == "flex"
    assert 0 < call["timeout"] <= 8


def test_worker_responses_caps_first_and_continuation_calls():
    client = OpenAIResponsesClient(_provider("responses"))
    endpoint = FakeEndpoint(SimpleNamespace(
        id="r1", output=[], output_text="submitted", usage=None,
    ))
    sdk = FakeSDK(endpoint, "responses")
    client._client = sdk
    client.configure_worker_limits(WorkerRequestLimits(456, time.monotonic() + 8))
    assert client.chat([{"role": "user", "content": "fixture"}]) == "submitted"
    assert client.submit_tool_outputs([NativeToolOutput("call-1", "fixture")]) == "submitted"
    assert sdk.retries == [0]
    assert len(endpoint.calls) == 2
    assert all(call["max_output_tokens"] == 456 for call in endpoint.calls)
    assert all(0 < call["timeout"] <= 8 for call in endpoint.calls)
    assert endpoint.calls[1]["previous_response_id"] == "r1"


def test_expired_worker_deadline_never_dispatches_sdk_request():
    client = OpenAIResponsesClient(_provider("responses"))
    endpoint = FakeEndpoint(None)
    sdk = FakeSDK(endpoint, "responses")
    client._client = sdk
    client.configure_worker_limits(WorkerRequestLimits(5, time.monotonic() - 1))
    with pytest.raises(TimeoutError, match="before SDK dispatch"):
        client.chat([{"role": "user", "content": "fixture"}])
    assert sdk.retries == [0]
    assert not endpoint.calls

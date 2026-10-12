"""Flex request routing and live runtime preference regression tests."""

import json
import logging
import time
from email.utils import formatdate
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI, RateLimitError

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.base import NativeToolOutput
from llm.openai_chat import OpenAIChatClient
from llm.openai_flex import FLEX_MAX_CAPACITY_RETRIES, flex_request_options
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from llm.worker_limits import WorkerRequestLimits
from runtime.state import ModelSettings


CLIENTS = [OpenAIChatClient, OpenAIResponsesClient]


def make_client(client_type, base_url="https://api.openai.com/v1"):
    provider = ProviderConfig(
        key="arbitrary-provider-name",
        label="Test",
        api_key="test-key",
        base_url=base_url,
        api_type="responses" if client_type is OpenAIResponsesClient else "chat_completions",
        default_model="o3",
        supports_model_listing=False,
    )
    client = client_type(provider)
    endpoint = Mock(return_value=SimpleNamespace(
        id="resp_test", output=[], output_text="answer",
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))],
    ))
    client._client.close()
    client._client = SimpleNamespace(
        responses=SimpleNamespace(create=endpoint),
        chat=SimpleNamespace(completions=SimpleNamespace(create=endpoint)),
    )
    client._client.with_options = Mock(return_value=client._client)
    return client, endpoint


@pytest.mark.parametrize("client_type", CLIENTS)
def test_flex_is_opt_in_and_changes_apply_without_rebuilding(client_type):
    client, endpoint = make_client(client_type)
    messages = [{"role": "user", "content": "hello"}]
    client.chat(messages)
    assert "service_tier" not in endpoint.call_args.kwargs
    assert endpoint.call_args.kwargs["timeout"] == 180.0

    settings = ModelSettings()
    assert settings.openai_flex is False
    client.configure_model_settings(settings)
    settings.openai_flex = True
    client.chat(messages)
    assert endpoint.call_args.kwargs["service_tier"] == "flex"
    assert endpoint.call_args.kwargs["timeout"] == 900.0

    settings.openai_flex = False
    client.chat(messages)
    assert "service_tier" not in endpoint.call_args.kwargs
    assert endpoint.call_args.kwargs["timeout"] == 180.0


def test_responses_tool_continuations_use_current_flex_setting():
    client, endpoint = make_client(OpenAIResponsesClient)
    settings = ModelSettings(openai_flex=True)
    client.configure_model_settings(settings)
    tools = [{"type": "function", "name": "test_tool", "parameters": {"type": "object"}}]
    client.chat([{"role": "user", "content": "hello"}], tools=tools, tool_choice="auto")
    outputs = [NativeToolOutput(call_id="call_test", output="done")]
    client.submit_tool_outputs(outputs)
    kwargs = endpoint.call_args.kwargs
    assert kwargs["service_tier"] == "flex"
    assert kwargs["timeout"] == 900.0
    assert kwargs["previous_response_id"] == "resp_test"
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["input"][0]["type"] == "function_call_output"

    settings.openai_flex = False
    client.submit_tool_outputs(outputs)
    assert "service_tier" not in endpoint.call_args.kwargs
    assert endpoint.call_args.kwargs["timeout"] == 180.0
    assert endpoint.call_args.kwargs["previous_response_id"] == "resp_test"


@pytest.mark.parametrize("base_url", [
    "http://localhost:1234/v1",
    "https://gateway.example/v1",
    "https://api.openai.com.example/v1",
    "https://example.openai.azure.com/openai/v1",
    "http://api.openai.com/v1",
])
def test_non_openai_endpoints_never_receive_flex(base_url):
    assert flex_request_options(base_url, ModelSettings(openai_flex=True)) == {}


@pytest.mark.parametrize("client_type", CLIENTS)
def test_sdk_environment_endpoint_override_is_respected(client_type, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    client, endpoint = make_client(client_type, base_url=None)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    client.chat([{"role": "user", "content": "hello"}])
    assert "service_tier" not in endpoint.call_args.kwargs
    assert endpoint.call_args.kwargs["timeout"] == 180.0


@pytest.mark.parametrize("client_type", CLIENTS)
def test_flex_errors_do_not_fall_back_to_standard(client_type):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = RuntimeError("Flex resource unavailable")
    with pytest.raises(RuntimeError, match="Flex resource unavailable"):
        client.chat([{"role": "user", "content": "hello"}])
    assert endpoint.call_count == 1
    assert endpoint.call_args.kwargs["service_tier"] == "flex"


def test_agent_binds_settings_initially_and_after_model_switch(tmp_path):
    settings = ModelSettings(openai_flex=True)
    state = SimpleNamespace(
        cwd=tmp_path,
        model_settings=settings,
        model_config=SimpleNamespace(
            provider_key="test", provider_label="Test", model="o3", api_type="responses",
        ),
    )
    first, first_endpoint = make_client(OpenAIResponsesClient)
    agent = Agent("system", state, first, tool_registry=ToolRegistry())
    first.chat([{"role": "user", "content": "hello"}])
    assert first_endpoint.call_args.kwargs["service_tier"] == "flex"

    other, other_endpoint = make_client(OpenAIChatClient, "https://gateway.example/v1")
    agent.set_llm(other)
    other.chat([{"role": "user", "content": "hello"}])
    assert "service_tier" not in other_endpoint.call_args.kwargs

    second, second_endpoint = make_client(OpenAIChatClient)
    agent.set_llm(second)
    second.chat([{"role": "user", "content": "hello"}])
    assert second_endpoint.call_args.kwargs["service_tier"] == "flex"
    settings.openai_flex = False
    second.chat([{"role": "user", "content": "hello"}])
    assert "service_tier" not in second_endpoint.call_args.kwargs


def capacity_error(code="flex_unavailable", error_type="resource_unavailable", headers=None):
    body = {"message": "Capacity refused", "type": error_type, "code": code}
    response = httpx.Response(
        429, headers=headers, json={"error": body},
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    return RateLimitError("Capacity refused", response=response, body=body)


@pytest.fixture
def flex_waits(monkeypatch):
    waits = []
    monkeypatch.setattr("llm.openai_flex.time.sleep", waits.append)
    monkeypatch.setattr("llm.openai_flex.random.uniform", lambda low, high: 1.0)
    return waits


@pytest.mark.parametrize("client_type", CLIENTS)
def test_capacity_refusal_is_retried_without_changing_request(client_type, flex_waits, caplog):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    success = endpoint.return_value
    success.service_tier = "flex"
    success.usage = SimpleNamespace(total_tokens=42)
    endpoint.side_effect = [capacity_error(), capacity_error(), success]
    with caplog.at_level(logging.DEBUG, logger="llm.openai_flex"):
        assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == [5.0, 10.0]
    assert endpoint.call_count == 3
    calls = [call.kwargs for call in endpoint.call_args_list]
    assert all(call == calls[0] for call in calls)
    assert calls[0]["service_tier"] == "flex"
    assert client.last_usage is success.usage  # Refused capacity has no billed generation.
    client._client.with_options.assert_called_once_with(max_retries=0)
    assert "staying on Flex" in caplog.text
    assert "actual_tier=flex" in caplog.text


@pytest.mark.parametrize("client_type", CLIENTS)
def test_capacity_retries_are_bounded_and_reraise_original_error(client_type, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    error = capacity_error()
    endpoint.side_effect = error
    with pytest.raises(RateLimitError) as caught:
        client.chat([{"role": "user", "content": "hello"}])
    assert caught.value is error
    assert flex_waits == [5.0, 10.0, 20.0, 40.0, 60.0]
    assert endpoint.call_count == 1 + FLEX_MAX_CAPACITY_RETRIES
    assert all(call.kwargs["service_tier"] == "flex" for call in endpoint.call_args_list)
    assert client.last_usage is None
    if client_type is OpenAIResponsesClient:
        assert client._last_response_id is None


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("code,error_type", [
    ("insufficient_quota", "insufficient_quota"),
    ("rate_limit_exceeded", "rate_limit_error"),
    (None, "rate_limit_error"),
])
def test_other_429_errors_get_no_additional_retries(client_type, code, error_type, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = capacity_error(code, error_type)
    with pytest.raises(RateLimitError):
        client.chat([{"role": "user", "content": "hello"}])
    assert endpoint.call_count == 1
    assert flex_waits == []
    client._client.with_options.assert_not_called()


def test_capacity_error_without_code_is_recognized_by_type(flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(None), endpoint.return_value]
    assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == [5.0]


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("base_url,flex", [
    ("https://api.openai.com/v1", False),
    ("https://gateway.example/v1", True),
])
def test_non_flex_dispatch_retains_sdk_behavior(client_type, base_url, flex, flex_waits):
    client, endpoint = make_client(client_type, base_url)
    client.configure_model_settings(ModelSettings(openai_flex=flex))
    endpoint.side_effect = capacity_error()
    with pytest.raises(RateLimitError):
        client.chat([{"role": "user", "content": "hello"}])
    assert endpoint.call_count == 1
    assert flex_waits == []
    client._client.with_options.assert_not_called()


@pytest.mark.parametrize("client_type", CLIENTS)
def test_worker_capacity_errors_remain_single_dispatch(client_type, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    client.configure_worker_limits(WorkerRequestLimits(32, time.monotonic() + 30))
    client._client.with_options.reset_mock()
    endpoint.side_effect = capacity_error()
    with pytest.raises(RateLimitError):
        client.chat([{"role": "user", "content": "hello"}])
    assert endpoint.call_count == 1
    assert flex_waits == []
    client._client.with_options.assert_not_called()


@pytest.mark.parametrize("worker", [False, True])
def test_tool_output_capacity_retries_preserve_chain_and_outputs(worker, flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    if worker:
        client.configure_worker_limits(WorkerRequestLimits(32, time.monotonic() + 30))
    tools = [{"type": "function", "name": "test_tool", "parameters": {"type": "object"}}]
    client.chat([{"role": "user", "content": "hello"}], tools=tools, tool_choice="auto")
    previous = client._last_response_id
    endpoint.reset_mock()
    error = capacity_error()
    success = SimpleNamespace(id="resp_next", output=[], output_text="done")
    endpoint.side_effect = [error, success]
    outputs = [NativeToolOutput(call_id="call_test", output="tool result")]
    if worker:
        with pytest.raises(RateLimitError):
            client.submit_tool_outputs(outputs)
        assert flex_waits == []
        assert client._last_response_id == previous
    else:
        assert client.submit_tool_outputs(outputs) == "done"
        assert flex_waits == [5.0]
        assert client._last_response_id == "resp_next"
    for call in endpoint.call_args_list:
        assert call.kwargs["previous_response_id"] == previous
        assert call.kwargs["input"] == [
            {"type": "function_call_output", "call_id": "call_test", "output": "tool result"},
        ]
        assert call.kwargs["tools"] == tools
        assert call.kwargs["tool_choice"] == "auto"
        assert call.kwargs["service_tier"] == "flex"


@pytest.mark.parametrize("headers,expected", [
    ({"retry-after": "30"}, 30.0),
    ({"retry-after-ms": "25000"}, 25.0),
    ({"retry-after": formatdate(1030, usegmt=True)}, 30.0),
    ({"retry-after": "invalid"}, 5.0),
    ({"retry-after": "nan"}, 5.0),
    ({"retry-after": "120"}, None),
    ({"x-should-retry": "false"}, None),
])
def test_capacity_retries_respect_server_guidance(headers, expected, flex_waits, monkeypatch):
    monkeypatch.setattr("llm.openai_flex.time.time", lambda: 1000.0)
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(headers=headers), endpoint.return_value]
    if expected is None:
        with pytest.raises(RateLimitError):
            client.chat([{"role": "user", "content": "hello"}])
        assert endpoint.call_count == 1
        assert flex_waits == []
    else:
        assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
        assert flex_waits == [expected]


@pytest.mark.parametrize("client_type", CLIENTS)
def test_real_sdk_does_not_multiply_additional_capacity_retries(client_type, flex_waits):
    requests = []

    def refuse(request):
        requests.append(json.loads(request.content))
        return httpx.Response(429, json={"error": {
            "message": "Capacity refused", "type": "resource_unavailable", "code": "flex_unavailable",
        }})

    client, _ = make_client(client_type)
    with OpenAI(api_key="test-key", http_client=httpx.Client(
        transport=httpx.MockTransport(refuse),
    )) as sdk:
        client._client = sdk
        client.configure_model_settings(ModelSettings(openai_flex=True))
        with pytest.raises(RateLimitError):
            client.chat([{"role": "user", "content": "hello"}])
        # Initial SDK dispatch: 1 + its existing two retries; then five slower,
        # single-dispatch attempts. No (SDK retries x capacity retries) loop.
        assert len(requests) == 3 + FLEX_MAX_CAPACITY_RETRIES
        assert all(request == requests[0] for request in requests)
        assert requests[0]["service_tier"] == "flex"
        assert flex_waits[-5:] == [5.0, 10.0, 20.0, 40.0, 60.0]
        assert sdk.max_retries == 2  # Original client's policy was not mutated.

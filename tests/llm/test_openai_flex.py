"""Flex request routing and live runtime preference regression tests."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI, RateLimitError

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.base import (
    REQUEST_RETRY_NOTE_PREFIX, NativeToolOutput, request_retry_diagnostic,
)
from llm.openai_chat import OpenAIChatClient
from llm.openai_flex import (
    FLEX_MAX_CAPACITY_RETRIES, FLEX_MAX_EXTRA_BACKOFF_SECONDS, flex_request_options,
)
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from llm.request_progress import (
    REQUEST_PROGRESS_PREFIX, notify_request_retry, request_progress_listener,
)
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
    ({"retry-after": "60"}, 60.0),
    ({"retry-after-ms": "61000"}, 61.0),
    ({"retry-after": "120"}, 120.0),
    ({"retry-after": formatdate(1120, usegmt=True)}, 120.0),
    ({"retry-after": "300"}, 300.0),
    ({"retry-after-ms": "300000"}, 300.0),
    ({"retry-after": "300.001"}, None),
    ({"retry-after": "301"}, None),
    ({"retry-after-ms": "300001"}, None),
    ({"retry-after": "inf"}, 5.0),
    ({"retry-after": "-1"}, 5.0),
    ({"retry-after-ms": "invalid", "retry-after": "120"}, 120.0),
    ({"retry-after-ms": "61000", "retry-after": "301"}, 61.0),
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
@pytest.mark.parametrize("headers,expected_waits", [
    ({}, [5.0, 10.0, 20.0, 40.0, 60.0]),
    ({"retry-after": "120"}, [120.0] * 2),
    ({"retry-after": "300"}, [300.0]),
])
def test_real_sdk_does_not_multiply_additional_capacity_retries(
    client_type, headers, expected_waits, flex_waits,
):
    requests = []

    def refuse(request):
        requests.append(json.loads(request.content))
        return httpx.Response(429, headers=headers, json={"error": {
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
        # Initial SDK dispatch: 1 + its existing two retries; then bounded,
        # single-dispatch attempts. No (SDK retries x capacity retries) loop.
        assert len(requests) == 3 + len(expected_waits)
        assert all(request == requests[0] for request in requests)
        assert requests[0]["service_tier"] == "flex"
        assert flex_waits[-len(expected_waits):] == expected_waits
        assert sum(expected_waits) <= FLEX_MAX_EXTRA_BACKOFF_SECONDS
        assert sdk.max_retries == 2  # Original client's policy was not mutated.


@pytest.mark.parametrize("headers,flex,allow,stop,expected_waits", [
    ({"x-should-retry": "false"}, True, True, "server_x_should_retry_false", []),
    ({"retry-after": "301"}, True, True, "server_retry_after_exceeds_300s", []),
    ({"retry-after-ms": "300001"}, True, True, "server_retry_after_exceeds_300s", []),
    ({"retry-after": "120"}, True, True, "extra_backoff_budget_exhausted", [120.0] * 2),
    ({"retry-after-ms": "61000"}, True, True, "extra_backoff_budget_exhausted", [61.0] * 4),
    ({"retry-after": "300"}, True, True, "extra_backoff_budget_exhausted", [300.0]),
    ({"retry-after": "250"}, True, True, "extra_backoff_budget_exhausted", [250.0]),
    ({"retry-after": "150"}, True, True, "extra_backoff_budget_exhausted", [150.0] * 2),
    ({"x-should-retry": "false", "retry-after": "120"}, True, True,
     "server_x_should_retry_false", []),
    ({"retry-after": "60"}, True, True, "retry_budget_exhausted", [60.0] * 5),
    ({}, True, True, "retry_budget_exhausted", [5.0, 10.0, 20.0, 40.0, 60.0]),
    ({}, False, True, "flex_not_explicitly_requested", []),
    ({}, True, False, "extra_retries_disabled", []),
])
def test_terminal_note_reports_actual_extra_attempts_and_policy_stop(
    headers, flex, allow, stop, expected_waits, flex_waits, monkeypatch,
):
    from llm.openai_flex import create_openai_request

    client, endpoint = make_client(OpenAIResponsesClient)
    error = capacity_error(headers=headers)
    original_text, original_body = str(error), error.body
    clock = [0.0]

    def sleep(delay):
        flex_waits.append(delay)
        clock[0] += delay

    def refuse(**kwargs):
        clock[0] += 2.0
        raise error

    monkeypatch.setattr("llm.openai_flex.time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=sleep, time=lambda: 1000.0,
    ))
    endpoint.side_effect = refuse
    kwargs = {"service_tier": "flex"} if flex else {}
    with pytest.raises(RateLimitError) as caught:
        create_openai_request(client._client, "responses", kwargs, allow_flex_retries=allow)
    assert caught.value is error
    assert str(error) == original_text and error.body is original_body
    assert flex_waits == expected_waits
    assert endpoint.call_count == 1 + len(expected_waits)
    note = request_retry_diagnostic(error)
    budget = FLEX_MAX_CAPACITY_RETRIES if flex and allow else 0
    assert note is not None and len(note) <= 512
    assert f"extra_retries={len(expected_waits)}/{budget}" in note
    assert f"extra_backoff={sum(expected_waits):.1f}s" in note
    assert f"elapsed={clock[0]:.1f}s" in note
    assert f"stop={stop}" in note
    assert "Capacity refused" not in note  # Never copy provider body/header text.
    if "retry-after" not in headers and "retry-after-ms" not in headers:
        assert "server_min_wait=none" in note
    if headers.get("retry-after") == "301":
        assert "server_min_wait=301s" in note


def test_later_header_can_stop_before_the_longer_backoffs(flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(), capacity_error(),
                            capacity_error(headers={"retry-after": "301"})]
    with pytest.raises(RateLimitError) as caught:
        client.chat([{"role": "user", "content": "hello"}])
    assert endpoint.call_count == 3 and flex_waits == [5.0, 10.0]
    note = request_retry_diagnostic(caught.value)
    assert note is not None
    assert "extra_retries=2/5" in note and "extra_backoff=15.0s" in note
    assert "stop=server_retry_after_exceeds_300s" in note


@pytest.mark.parametrize("client_type,continuation", [
    (OpenAIChatClient, False), (OpenAIResponsesClient, False),
    (OpenAIResponsesClient, True),
])
def test_agent_displays_only_bounded_retry_note_and_preserves_pending_chain(
    client_type, continuation, tmp_path, flex_waits, monkeypatch,
):
    client, endpoint = make_client(client_type)
    state = SimpleNamespace(
        cwd=tmp_path, model_settings=ModelSettings(openai_flex=True),
        model_config=SimpleNamespace(provider_key="test", provider_label="Test",
                                     model="o3", api_type=client.api_type),
    )
    errors = []
    agent = Agent("system", state, client, tool_registry=ToolRegistry(), on_error=errors.append)
    monkeypatch.setattr(agent, "_messages_with_context", lambda: [])
    if continuation:
        client._last_response_id = "resp_pending"
        pending = [(SimpleNamespace(status="success", observation="done"),
                    SimpleNamespace(id="call_pending"))]
        agent._pending_native_tool_calls = pending
    error = capacity_error(headers={"retry-after": "301"})
    error.add_note("PRIVATE_UNRELATED_NOTE_CANARY")
    endpoint.side_effect = error
    result = agent.step("hello")
    assert result.startswith("Error: Model request failed: Capacity refused\n")
    assert "Request retry diagnostic: Flex capacity; extra_retries=0/5" in result
    assert "stop=server_retry_after_exceeds_300s" in result
    assert "server_min_wait=301s" in result
    assert "PRIVATE_UNRELATED_NOTE_CANARY" not in result
    assert errors == [result] and flex_waits == [] and endpoint.call_count == 1
    if continuation:
        assert client._last_response_id == "resp_pending"
        assert agent._pending_native_tool_calls is pending
        assert endpoint.call_args.kwargs["previous_response_id"] == "resp_pending"


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("server_wait", [61.0, 120.0, 300.0])
def test_long_server_wait_can_recover_on_flex(client_type, server_wait, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [
        capacity_error(headers={"retry-after": str(server_wait)}), endpoint.return_value,
    ]
    assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == [server_wait] and endpoint.call_count == 2
    assert endpoint.call_args_list[0].kwargs == endpoint.call_args_list[1].kwargs
    assert endpoint.call_args.kwargs["service_tier"] == "flex"
    client._client.with_options.assert_called_once_with(max_retries=0)


def test_server_minimum_on_later_refusal_is_not_capped_to_ordinary_backoff(flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(), capacity_error(),
                            capacity_error(headers={"retry-after": "120"}), endpoint.return_value]
    assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == [5.0, 10.0, 120.0] and endpoint.call_count == 4


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("server_waits", [[300.0], [150.0, 150.0], [120.0, 120.0, 60.0]])
def test_success_is_allowed_after_exactly_consuming_extra_wait_budget(
    client_type, server_waits, flex_waits,
):
    assert FLEX_MAX_EXTRA_BACKOFF_SECONDS == 300.0
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [
        *(capacity_error(headers={"retry-after": str(wait)}) for wait in server_waits),
        endpoint.return_value,
    ]
    assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == server_waits and endpoint.call_count == 1 + len(server_waits)
    assert sum(flex_waits) == FLEX_MAX_EXTRA_BACKOFF_SECONDS


@pytest.mark.parametrize("client_type", CLIENTS)
def test_later_server_minimum_is_not_shortened_to_fit_remaining_budget(client_type, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(), capacity_error(headers={"retry-after": "300"})]
    with pytest.raises(RateLimitError) as caught:
        client.chat([{"role": "user", "content": "hello"}])
    assert flex_waits == [5.0] and endpoint.call_count == 2
    note = request_retry_diagnostic(caught.value)
    assert note is not None
    assert "extra_retries=1/5" in note and "extra_backoff=5.0s" in note
    assert "stop=extra_backoff_budget_exhausted" in note
    assert "server_min_wait=300s" in note


@pytest.mark.parametrize("worker", [False, True])
def test_long_server_wait_does_not_enable_ineligible_retries(worker, flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=worker))
    if worker:
        client.configure_worker_limits(WorkerRequestLimits(32, time.monotonic() + 30))
    endpoint.side_effect = capacity_error(headers={"retry-after": "120"})
    with pytest.raises(RateLimitError):
        client.chat([{"role": "user", "content": "hello"}])
    assert flex_waits == [] and endpoint.call_count == 1


@pytest.mark.parametrize("client_type,continuation", [
    (OpenAIChatClient, False), (OpenAIResponsesClient, False),
    (OpenAIResponsesClient, True),
])
@pytest.mark.parametrize("recover", [False, True])
def test_agent_reports_wait_before_sleep_without_changing_conversation(
    client_type, continuation, recover, tmp_path, flex_waits, monkeypatch,
):
    client, endpoint = make_client(client_type)
    state = SimpleNamespace(
        cwd=tmp_path, model_settings=ModelSettings(openai_flex=True),
        model_config=SimpleNamespace(provider_key="test", provider_label="Test",
                                     model="o3", api_type=client.api_type),
    )
    notices = []
    agent = Agent("system", state, client, tool_registry=ToolRegistry(), on_tool=notices.append)
    monkeypatch.setattr(agent, "_messages_with_context", lambda: [])
    pending = [(SimpleNamespace(status="success", observation="done"),
                SimpleNamespace(id="call_pending"))]
    if continuation:
        client._last_response_id = "resp_pending"
        agent._pending_native_tool_calls = pending
    refusal = capacity_error(headers={"retry-after": "300", "x-private": "PRIVATE_CANARY"})
    endpoint.side_effect = [refusal, endpoint.return_value if recover else refusal]

    def sleep(delay):
        # Notification must already be delivered when the wait starts.
        assert endpoint.call_count == 1
        assert len(notices) == 1
        assert "waiting 5 minutes (300 seconds) before retry 1/5" in notices[0]
        flex_waits.append(delay)

    monkeypatch.setattr("llm.openai_flex.time.sleep", sleep)
    result = agent.step("hello")
    assert flex_waits == [300.0] and endpoint.call_count == 2
    assert len(notices) == 1 and notices[0].startswith(REQUEST_PROGRESS_PREFIX)
    assert "PRIVATE_CANARY" not in notices[0] and "Capacity refused" not in notices[0]
    assert all(call.kwargs["service_tier"] == "flex" for call in endpoint.call_args_list)
    assert endpoint.call_args_list[0].kwargs == endpoint.call_args_list[1].kwargs
    assert all("waiting 5 minutes" not in str(message) for message in agent.messages)
    assert "waiting 5 minutes" not in result
    if recover:
        assert result == "answer"
    else:
        assert "stop=extra_backoff_budget_exhausted" in result
    if continuation:
        assert agent._pending_native_tool_calls == (None if recover else pending)
    notify_request_retry(300.0, 1, 5)  # Request-scoped listener was restored.
    assert len(notices) == 1


@pytest.mark.parametrize("delay,duration", [
    (5.25, "5.2 seconds"), (60.0, "1 minute (60 seconds)"),
    (120.0, "2 minutes (120 seconds)"), (300.0, "5 minutes (300 seconds)"),
])
def test_retry_notice_formats_actual_delay(delay, duration):
    notices = []
    with request_progress_listener(notices.append):
        notify_request_retry(delay, 2, 5)
    assert notices == [
        REQUEST_PROGRESS_PREFIX + f"Flex capacity unavailable — waiting {duration} "
        "before retry 2/5; staying on Flex.",
    ]


def test_request_notice_listener_is_scoped_restored_and_not_shared_with_other_threads():
    outer, inner = [], []
    with request_progress_listener(outer.append):
        notify_request_retry(5.0, 1, 5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(notify_request_retry, 5.0, 1, 5).result()
        with pytest.raises(RuntimeError), request_progress_listener(inner.append):
            notify_request_retry(10.0, 2, 5)
            raise RuntimeError("fixture")
        notify_request_retry(20.0, 3, 5)
    notify_request_retry(40.0, 4, 5)
    assert len(outer) == 2 and len(inner) == 1
    assert "before retry 1/5" in outer[0] and "before retry 3/5" in outer[1]
    assert "before retry 2/5" in inner[0]


@pytest.mark.parametrize("client_type", CLIENTS)
def test_broken_notice_callback_does_not_fail_or_duplicate_request(client_type, flex_waits):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    endpoint.side_effect = [capacity_error(headers={"retry-after": "300"}), endpoint.return_value]

    def broken(message):
        raise RuntimeError("display disconnected")

    with request_progress_listener(broken):
        assert client.chat([{"role": "user", "content": "hello"}]) == "answer"
    assert flex_waits == [300.0] and endpoint.call_count == 2


@pytest.mark.parametrize("headers,flex,worker,code", [
    ({"x-should-retry": "false"}, True, False, "flex_unavailable"),
    ({"retry-after": "301"}, True, False, "flex_unavailable"),
    ({"retry-after": "300"}, False, False, "flex_unavailable"),
    ({"retry-after": "300"}, True, True, "flex_unavailable"),
    ({"retry-after": "300"}, True, False, "insufficient_quota"),
])
def test_no_wait_notice_when_policy_will_not_retry(headers, flex, worker, code, flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=flex))
    if worker:
        client.configure_worker_limits(WorkerRequestLimits(32, time.monotonic() + 30))
    endpoint.side_effect = capacity_error(code=code, headers=headers)
    notices = []
    with request_progress_listener(notices.append), pytest.raises(RateLimitError):
        client.chat([{"role": "user", "content": "hello"}])
    assert notices == [] and flex_waits == [] and endpoint.call_count == 1


def test_diagnostic_reader_ignores_unrelated_oversized_or_multiline_notes():
    error = RuntimeError("original")
    for note in ("PRIVATE_NOTE_CANARY", REQUEST_RETRY_NOTE_PREFIX + "x" * 513,
                 REQUEST_RETRY_NOTE_PREFIX + "line\nPRIVATE_NOTE_CANARY",
                 REQUEST_RETRY_NOTE_PREFIX + "line\rPRIVATE_NOTE_CANARY"):
        error.add_note(note)
    assert request_retry_diagnostic(error) is None
    error.add_note(REQUEST_RETRY_NOTE_PREFIX + "fixed safe summary")
    assert request_retry_diagnostic(error) == REQUEST_RETRY_NOTE_PREFIX + "fixed safe summary"
    assert str(error) == "original"


def test_noncapacity_error_does_not_receive_flex_note(flex_waits):
    client, endpoint = make_client(OpenAIResponsesClient)
    client.configure_model_settings(ModelSettings(openai_flex=True))
    error = capacity_error("rate_limit_exceeded", "rate_limit_error")
    endpoint.side_effect = error
    with pytest.raises(RateLimitError) as caught:
        client.chat([{"role": "user", "content": "hello"}])
    assert caught.value is error and request_retry_diagnostic(error) is None
    assert flex_waits == [] and endpoint.call_count == 1

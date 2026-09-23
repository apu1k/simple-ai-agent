"""Reasoning-effort request routing and live preference regression tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.base import NativeToolOutput
from llm.openai_chat import OpenAIChatClient
from llm.openai_reasoning import reasoning_request_options
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from runtime.state import ModelSettings, OPENAI_REASONING_EFFORTS


CLIENTS = [OpenAIChatClient, OpenAIResponsesClient]
MESSAGES = [{"role": "user", "content": "hello"}]


def make_client(client_type, base_url="https://api.openai.com/v1"):
    client = client_type(ProviderConfig(
        key="test", label="Test", api_key="test-key", base_url=base_url,
        api_type="responses" if client_type is OpenAIResponsesClient else "chat_completions",
        default_model="test-model", supports_model_listing=False,
    ))
    endpoint = Mock(return_value=SimpleNamespace(
        id="resp_test", output=[], output_text="answer",
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))],
    ))
    client._client.close()
    client._client = SimpleNamespace(
        responses=SimpleNamespace(create=endpoint),
        chat=SimpleNamespace(completions=SimpleNamespace(create=endpoint)),
    )
    return client, endpoint


def assert_effort(kwargs, client_type, effort):
    key = "reasoning" if client_type is OpenAIResponsesClient else "reasoning_effort"
    other_key = "reasoning_effort" if key == "reasoning" else "reasoning"
    assert other_key not in kwargs
    if effort is None:
        assert key not in kwargs
    else:
        assert kwargs[key] == ({"effort": effort} if key == "reasoning" else effort)


@pytest.mark.parametrize("client_type", CLIENTS)
def test_default_and_all_efforts_apply_live_with_flex(client_type):
    client, endpoint = make_client(client_type)
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, None)
    settings = ModelSettings()
    assert settings.openai_reasoning_effort is None
    client.configure_model_settings(settings)
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, None)

    settings.openai_flex = True
    for effort in (*OPENAI_REASONING_EFFORTS, None):
        settings.openai_reasoning_effort = effort
        client.chat(MESSAGES)
        kwargs = endpoint.call_args.kwargs
        assert_effort(kwargs, client_type, effort)
        assert kwargs["service_tier"] == "flex"
        assert kwargs["timeout"] == 900.0

    settings.openai_flex = False
    settings.openai_reasoning_effort = "high"
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, "high")
    assert "service_tier" not in endpoint.call_args.kwargs
    assert endpoint.call_args.kwargs["timeout"] == 180.0


def test_tool_continuations_use_current_effort_without_resetting_chain():
    client, endpoint = make_client(OpenAIResponsesClient)
    settings = ModelSettings(openai_reasoning_effort="high")
    client.configure_model_settings(settings)
    tools = [{"type": "function", "name": "test_tool", "parameters": {"type": "object"}}]
    client.chat(MESSAGES, tools=tools, tool_choice="auto")
    for effort in ("high", "low", "none", None):
        settings.openai_reasoning_effort = effort
        client.submit_tool_outputs([NativeToolOutput(call_id="call_test", output="done")])
        kwargs = endpoint.call_args.kwargs
        assert_effort(kwargs, OpenAIResponsesClient, effort)
        assert kwargs["previous_response_id"] == "resp_test"
        assert kwargs["tools"] == tools
        assert kwargs["tool_choice"] == "auto"
        assert kwargs["input"][0]["type"] == "function_call_output"


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("base_url", [
    "http://localhost:1234/v1", "https://gateway.example/v1",
    "https://api.openai.com.example/v1", "https://example.openai.azure.com/openai/v1",
    "http://api.openai.com/v1",
])
def test_non_openai_requests_are_unchanged(client_type, base_url):
    client, endpoint = make_client(client_type, base_url)
    client.configure_model_settings(ModelSettings(openai_reasoning_effort="high"))
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, None)
    if client_type is OpenAIResponsesClient:
        client.submit_tool_outputs([NativeToolOutput(call_id="call_test", output="done")])
        assert_effort(endpoint.call_args.kwargs, client_type, None)


@pytest.mark.parametrize("client_type", CLIENTS)
def test_sdk_environment_endpoint_override_is_respected(client_type, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    client, endpoint = make_client(client_type, base_url=None)
    client.configure_model_settings(ModelSettings(openai_reasoning_effort="high"))
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, None)


@pytest.mark.parametrize("client_type", CLIENTS)
def test_max_effort_is_forwarded_unchanged(client_type):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_reasoning_effort="max"))
    client.chat(MESSAGES)
    assert_effort(endpoint.call_args.kwargs, client_type, "max")


@pytest.mark.parametrize("client_type", CLIENTS)
def test_unsupported_effort_errors_are_not_silently_retried(client_type):
    client, endpoint = make_client(client_type)
    client.configure_model_settings(ModelSettings(openai_reasoning_effort="xhigh"))
    endpoint.side_effect = RuntimeError("Unsupported reasoning effort")
    with pytest.raises(RuntimeError, match="Unsupported reasoning effort"):
        client.chat(MESSAGES)
    assert endpoint.call_count == 1
    assert_effort(endpoint.call_args.kwargs, client_type, "xhigh")


@pytest.mark.parametrize("api_type", ["completions", "gemini_vertex"])
def test_other_apis_are_unchanged(api_type):
    assert reasoning_request_options(
        "https://api.openai.com/v1", ModelSettings(openai_reasoning_effort="high"), api_type,
    ) == {}


def test_invalid_effort_is_rejected():
    settings = ModelSettings()
    settings.openai_reasoning_effort = "invalid"
    with pytest.raises(ValueError, match="Invalid OpenAI reasoning effort"):
        reasoning_request_options("https://api.openai.com/v1", settings, "responses")


def test_agent_preserves_preference_across_model_and_provider_switches(tmp_path):
    settings = ModelSettings(openai_reasoning_effort="high")
    state = SimpleNamespace(
        cwd=tmp_path, model_settings=settings,
        model_config=SimpleNamespace(
            provider_key="test", provider_label="Test", model="test-model", api_type="responses",
        ),
    )
    first, first_endpoint = make_client(OpenAIResponsesClient)
    agent = Agent("system", state, first, tool_registry=ToolRegistry())
    first.chat(MESSAGES)
    assert_effort(first_endpoint.call_args.kwargs, OpenAIResponsesClient, "high")
    other, other_endpoint = make_client(OpenAIChatClient, "https://gateway.example/v1")
    agent.set_llm(other)
    other.chat(MESSAGES)
    assert_effort(other_endpoint.call_args.kwargs, OpenAIChatClient, None)
    second, second_endpoint = make_client(OpenAIChatClient)
    agent.set_llm(second)
    second.chat(MESSAGES)
    assert_effort(second_endpoint.call_args.kwargs, OpenAIChatClient, "high")
    settings.openai_reasoning_effort = None
    second.chat(MESSAGES)
    assert_effort(second_endpoint.call_args.kwargs, OpenAIChatClient, None)

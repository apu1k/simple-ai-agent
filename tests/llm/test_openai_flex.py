"""Flex request routing and live runtime preference regression tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.base import NativeToolOutput
from llm.openai_chat import OpenAIChatClient
from llm.openai_flex import flex_request_options
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
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

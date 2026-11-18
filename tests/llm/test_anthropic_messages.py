"""Offline coverage at the real Anthropic SDK/HTTP boundary."""
import json
from dataclasses import replace

import httpx2
import pytest
from anthropic import BadRequestError

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from llm import anthropic_messages
from llm.base import NativeToolOutput
from llm.model_listing import list_models
from llm.providers import ProviderConfig, create_llm_client, load_providers
from runtime.state import AgentState, ModelConfig, ModelSettings

_MODEL = "claude-opus-5-5"
_PROVIDER = ProviderConfig("anthropic", "Anthropic Claude", "test-key-only",
                           "https://api.anthropic.com/v1/messages", "anthropic_messages", _MODEL, True)


@pytest.fixture
def http(monkeypatch):
    requests = []
    responses = []

    def dispatch(request):
        requests.append(request)
        return responses.pop(0)(request)

    def client(**options):
        assert options["follow_redirects"] is False
        return httpx2.Client(transport=httpx2.MockTransport(dispatch), **options)

    monkeypatch.setattr(anthropic_messages, "DefaultHttpxClient", client)
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    return requests, responses


def _stream(*blocks, stop="end_turn"):
    events = [{"type": "message_start", "message": {
        "id": "msg_fixture", "type": "message", "role": "assistant", "model": _MODEL,
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 20, "output_tokens": 1},
    }}]
    for index, block in enumerate(blocks):
        block = dict(block)
        arguments = block.pop("input", None)
        if arguments is not None:
            block["input"] = {}
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        if arguments is not None:
            events.append({"type": "content_block_delta", "index": index, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(arguments),
            }})
        events.append({"type": "content_block_stop", "index": index})
    events.extend([
        {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
         "usage": {"output_tokens": 11}},
        {"type": "message_stop"},
    ])
    payload = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return lambda request: httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=payload)


def _text(text):
    return {"type": "text", "text": text}


def _tool(call_id, name, **arguments):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


@pytest.mark.parametrize("base", [None, "https://api.anthropic.com", "https://api.anthropic.com/v1/",
                                  "https://api.anthropic.com/v1/messages"])
def test_chat_uses_native_endpoint_and_appends_no_openai_settings(http, base):
    requests, responses = http
    responses.append(_stream(_text("Hello, "), _text("world")))
    client = create_llm_client(replace(_PROVIDER, base_url=base), "claude-chosen")
    client.configure_model_settings(ModelSettings(openai_reasoning_effort="max", openai_flex=True))
    assert client.chat([{"role": "system", "content": "Be useful"},
                        {"role": "user", "content": "Hello"}]) == "Hello, world"
    assert client.last_usage.output_tokens == 11
    request, = requests
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["authorization"] == "Bearer test-key-only"
    payload = json.loads(request.content)
    assert payload == {
        "model": "claude-chosen", "max_tokens": 4096, "stream": True,
        "system": "Be useful", "messages": [{"role": "user", "content": "Hello"}],
    }


def test_all_effort_levels_use_output_config_without_forcing_thinking(http):
    requests, responses = http
    levels = ("low", "medium", "high", "xhigh", "max", None)
    responses.extend(_stream(_text("OK")) for _ in levels)
    client = create_llm_client(_PROVIDER, _MODEL)
    settings = ModelSettings()
    client.configure_model_settings(settings)
    for effort in levels:
        settings.anthropic_reasoning_effort = effort
        client.chat([{"role": "user", "content": "Hi"}])
    payloads = [json.loads(request.content) for request in requests]
    assert [payload.get("output_config") for payload in payloads] == [
        {"effort": level} if level is not None else None for level in levels
    ]
    assert all("thinking" not in payload for payload in payloads)


def test_no_retry_without_effort_when_provider_rejects_it(http):
    requests, responses = http
    responses.append(lambda request: httpx2.Response(400, json={
        "type": "error", "error": {"type": "invalid_request_error", "message": "Effort unsupported"},
    }))
    client = create_llm_client(_PROVIDER, "older-model")
    client.configure_model_settings(ModelSettings(anthropic_reasoning_effort="max"))
    with pytest.raises(BadRequestError, match="Effort unsupported"):
        client.chat([{"role": "user", "content": "Hi"}])
    assert len(requests) == 1


def test_agent_native_tool_batch_replays_signed_blocks_but_keeps_them_out_of_history(http, tmp_path):
    requests, responses = http
    signed = {"type": "thinking", "thinking": "not for the transcript", "signature": "opaque-signature"}
    redacted = {"type": "redacted_thinking", "data": "opaque-data"}
    returned = [_text("Checking."), _tool("toolu_1", "echo", value="OK"), _tool("toolu_2", "absent")]
    responses.extend([_stream(signed, redacted, *returned, stop="tool_use"),
                      _stream(_text("Done.")), _stream(_text("Next."))])
    registry = ToolRegistry()
    registry.register(ToolSpec(name="echo", description="Echo a value", parameters={"value": "text"},
                               function=lambda value: value, requires_state=False))
    state = AgentState(tmp_path, ModelConfig("anthropic", "Anthropic Claude", _MODEL,
                                             None, None, "anthropic_messages"))
    state.model_settings.anthropic_reasoning_effort = "high"
    client = create_llm_client(_PROVIDER, _MODEL)
    agent = Agent("Fixture prompt", state, client, tool_registry=registry)
    assert agent.step("Run it") == "Done."
    assert agent.step("Follow up") == "Next."
    first, second, third = [json.loads(request.content) for request in requests]
    assert first["tools"][0]["input_schema"]["required"] == ["value"]
    assert first["tool_choice"] == {"type": "auto"}
    assert second["output_config"] == {"effort": "high"}
    assert second["messages"][-2] == {"role": "assistant", "content": [signed, redacted, *returned]}
    results = second["messages"][-1]
    assert results["role"] == "user"
    ok, error = results["content"]
    assert ok == {"type": "tool_result", "tool_use_id": "toolu_1", "content": "OK", "is_error": False}
    assert error["type"] == "tool_result" and error["tool_use_id"] == "toolu_2" and error["is_error"] is True
    for context in (agent.messages, third["messages"]):
        dumped = json.dumps(context)
        assert "opaque-signature" not in dumped and "opaque-data" not in dumped
        assert "not for the transcript" not in dumped
        assert "Tool batch execution report" in dumped


def test_truncated_tool_call_is_not_exposed_to_the_agent(http):
    _, responses = http
    responses.append(_stream(_tool("toolu_1", "echo", value="unfinished"), stop="max_tokens"))
    client = create_llm_client(_PROVIDER, _MODEL)
    with pytest.raises(ValueError, match="output token limit"):
        client.chat([{"role": "user", "content": "Hi"}])
    with pytest.raises(ValueError, match="no pending"):
        client.submit_tool_outputs([NativeToolOutput("toolu_1", "result")])


def test_lists_all_model_pages_through_same_service_root(http):
    requests, responses = http

    def page(ids, more):
        return lambda request: httpx2.Response(200, json={
            "data": [{"id": name, "type": "model", "created_at": "2026-01-01T00:00:00Z",
                      "display_name": name} for name in ids],
            "first_id": ids[0], "last_id": ids[-1], "has_more": more,
        })

    responses.extend([page(["claude-z"], True), page(["claude-a", "claude-z"], False)])
    provider = replace(_PROVIDER, base_url="https://example.test/proxy/v1/messages")
    assert list_models(provider) == ["claude-a", "claude-z"]
    assert [request.url.path for request in requests] == ["/proxy/v1/models"] * 2
    assert requests[1].url.params["after_id"] == "claude-z"


def test_environment_enables_provider_for_existing_toml(monkeypatch, tmp_path):
    config = tmp_path / "providers.toml"
    config.write_text('[[providers]]\nkey="openai"\nlabel="Existing"\napi_type="responses"\n', encoding="utf-8")
    monkeypatch.setattr("llm.providers.PROVIDERS_FILE", config)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-only")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", _PROVIDER.base_url)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_MODEL", _MODEL)
    providers = load_providers()
    assert providers["openai"].label == "Existing"
    assert replace(providers["anthropic"], api_key_envs=()) == _PROVIDER
    monkeypatch.setattr("runtime.bootstrap.PROVIDERS", providers)
    from runtime.bootstrap import _startup_provider

    assert _startup_provider() == providers["anthropic"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "anthropic" not in load_providers()

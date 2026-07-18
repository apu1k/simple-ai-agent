"""Tests for provider-specific model catalogue backends."""

from types import SimpleNamespace

from llm import model_listing
from llm.providers import ProviderConfig


def _provider(api_type="gemini_vertex", **overrides):
    values = {
        "key": "test",
        "label": "Test provider",
        "api_key": None,
        "base_url": None,
        "api_type": api_type,
        "default_model": "gemini-2.5-flash",
        "supports_model_listing": True,
        "project": "test-project",
        "location": "us-central1",
    }
    values.update(overrides)
    return ProviderConfig(**values)


def test_gemini_listing_normalizes_and_filters_generation_models(monkeypatch):
    listed = [
        SimpleNamespace(
            name="publishers/google/models/gemini-2.5-pro",
            supported_actions=["generateContent"],
        ),
        SimpleNamespace(
            name="publishers/google/models/gemini-2.5-flash",
            supported_actions=None,
        ),
        SimpleNamespace(
            name="publishers/google/models/gemini-embedding-001",
            supported_actions=None,
        ),
        SimpleNamespace(
            name="publishers/google/models/gemini-specialized",
            supported_actions=["predict"],
        ),
        SimpleNamespace(
            name="publishers/google/models/imagen-4.0-generate-001",
            supported_actions=["generateContent"],
        ),
    ]
    models_api = SimpleNamespace(list=lambda **kwargs: listed)
    fake_client = SimpleNamespace(models=models_api)
    monkeypatch.setattr(
        model_listing,
        "_create_gemini_vertex_client",
        lambda provider: fake_client,
    )

    result = model_listing._list_gemini_vertex_models(
        _provider(),
        timeout=4.5,
        max_retries=2,
    )

    assert result == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_gemini_listing_passes_paging_timeout_and_retry_config(monkeypatch):
    captured = {}

    def list_models(**kwargs):
        captured.update(kwargs)
        return []

    fake_client = SimpleNamespace(models=SimpleNamespace(list=list_models))
    monkeypatch.setattr(
        model_listing,
        "_create_gemini_vertex_client",
        lambda provider: fake_client,
    )

    model_listing._list_gemini_vertex_models(
        _provider(),
        timeout=4.5,
        max_retries=2,
    )

    assert captured == {
        "config": {
            "page_size": 100,
            "query_base": True,
            "http_options": {
                "timeout": 4500,
                "retry_options": {"attempts": 3},
            },
        }
    }


def test_openai_compatible_listing_remains_available(monkeypatch):
    captured = {}
    fake_client = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: SimpleNamespace(data=[
                SimpleNamespace(id="model-b"),
                SimpleNamespace(id="model-a"),
                SimpleNamespace(id="model-a"),
            ])
        )
    )

    def create_client(provider, **kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(model_listing, "_create_openai_client", create_client)
    provider = _provider(
        api_type="chat_completions",
        api_key="test-key",
        base_url="https://example.test/v1",
    )

    result = model_listing.list_models(provider, timeout=3.0, max_retries=1)

    assert result == ["model-a", "model-b"]
    assert captured == {"timeout": 3.0, "max_retries": 1}


def test_listing_backend_can_be_registered_for_future_provider(monkeypatch):
    provider = _provider(api_type="anthropic")
    monkeypatch.setitem(
        model_listing._LISTERS,
        "anthropic",
        lambda provider, **kwargs: ["claude-test"],
    )

    assert model_listing.list_models(provider) == ["claude-test"]

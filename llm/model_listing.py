"""Provider-specific model discovery backends.

Model listing is intentionally separate from chat clients: some providers share
an inference protocol while exposing a different model catalogue. Add future
backends here and register them in ``_LISTERS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from llm.providers import ProviderConfig


ModelLister = Callable[..., list[str]]


def list_models(
    provider: "ProviderConfig",
    *,
    timeout: float = 6.0,
    max_retries: int = 0,
) -> list[str]:
    """List usable model IDs through the provider's catalogue API."""
    lister = _LISTERS.get(provider.api_type)
    if lister is None:
        raise ValueError(
            f"No model-listing backend for api_type '{provider.api_type}'."
        )
    return lister(provider, timeout=timeout, max_retries=max_retries)


def _create_openai_client(provider: "ProviderConfig", **kwargs):
    from openai import OpenAI

    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    return OpenAI(api_key=provider.api_key, **kwargs)


def _list_openai_models(
    provider: "ProviderConfig",
    *,
    timeout: float,
    max_retries: int,
) -> list[str]:
    client = _create_openai_client(
        provider,
        timeout=timeout,
        max_retries=max_retries,
    )
    return sorted({model.id for model in client.models.list().data if model.id})


def _create_gemini_vertex_client(provider: "ProviderConfig"):
    if not provider.project:
        raise ValueError("Gemini Vertex model listing requires a Google Cloud project ID.")
    if not provider.location:
        raise ValueError("Gemini Vertex model listing requires a Google Cloud location.")

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Gemini model listing requires the 'google-genai' package."
        ) from exc

    return genai.Client(
        vertexai=True,
        project=provider.project,
        location=provider.location,
    )


def _vertex_model_id(name: str) -> str:
    """Convert a Vertex resource name to the ID accepted by generate_content."""
    marker = "/models/"
    if marker in name:
        return name.rsplit(marker, 1)[1]
    return name


def _is_gemini_generation_model(model) -> bool:
    name = _vertex_model_id(str(getattr(model, "name", "") or ""))
    if not name.startswith("gemini-") or "embedding" in name.lower():
        return False

    actions = getattr(model, "supported_actions", None)
    if not actions:
        return True
    normalized_actions = {str(action).lower() for action in actions}
    return "generatecontent" in normalized_actions


def _list_gemini_vertex_models(
    provider: "ProviderConfig",
    *,
    timeout: float,
    max_retries: int,
) -> list[str]:
    client = _create_gemini_vertex_client(provider)
    models = client.models.list(config={
        "page_size": 100,
        "query_base": True,
        "http_options": {
            "timeout": max(1, int(timeout * 1000)),
            "retry_options": {"attempts": max(1, max_retries + 1)},
        },
    })
    return sorted({
        _vertex_model_id(model.name)
        for model in models
        if getattr(model, "name", None) and _is_gemini_generation_model(model)
    })


_LISTERS: dict[str, ModelLister] = {
    "chat_completions": _list_openai_models,
    "responses": _list_openai_models,
    "completions": _list_openai_models,
    "gemini_vertex": _list_gemini_vertex_models,
}

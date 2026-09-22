"""Opt-in reasoning effort for direct OpenAI requests."""

from __future__ import annotations

from urllib.parse import urlsplit

from runtime.state import ApiType, ModelSettings, OPENAI_REASONING_EFFORTS


def reasoning_request_options(
    base_url: str, settings: ModelSettings | None, api_type: ApiType,
) -> dict:
    """Omit defaults and leave third-party endpoints unchanged.

    OpenAI validates model-specific effort support. Do not silently downgrade
    unsupported choices or retry without the user's requested effort.
    """
    if settings is None or settings.openai_reasoning_effort is None:
        return {}
    url = urlsplit(base_url)
    if url.scheme != "https" or url.hostname != "api.openai.com":
        return {}
    effort = settings.openai_reasoning_effort
    if effort not in OPENAI_REASONING_EFFORTS:
        raise ValueError(f"Invalid OpenAI reasoning effort: {effort!r}")
    if api_type == "responses":
        return {"reasoning": {"effort": effort}}
    if api_type == "chat_completions":
        return {"reasoning_effort": effort}
    return {}

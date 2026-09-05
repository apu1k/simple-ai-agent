"""Shared, opt-in Flex request options for the direct OpenAI API."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from runtime.state import ModelSettings


FLEX_REQUEST_TIMEOUT_SECONDS = 900.0


def flex_request_options(base_url: str, settings: ModelSettings | None) -> dict:
    """Leave default requests and third-party OpenAI-compatible APIs unchanged.

    Use the SDK's resolved URL (including OPENAI_BASE_URL), not provider names
    or model-name heuristics. OpenAI validates model/account Flex availability;
    errors must not silently fall back to a more expensive service tier.
    """
    if settings is None or not settings.openai_flex:
        return {}
    url = urlsplit(base_url)
    if url.scheme != "https" or url.hostname != "api.openai.com":
        return {}
    return {"service_tier": "flex", "timeout": FLEX_REQUEST_TIMEOUT_SECONDS}

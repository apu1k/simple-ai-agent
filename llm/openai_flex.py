"""Shared, opt-in Flex request options for the direct OpenAI API."""

from __future__ import annotations

import logging
import math
import random
import time
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from openai import OpenAI, RateLimitError

if TYPE_CHECKING:
    from runtime.state import ModelSettings


FLEX_REQUEST_TIMEOUT_SECONDS = 900.0
FLEX_MAX_CAPACITY_RETRIES = 5
FLEX_INITIAL_RETRY_DELAY_SECONDS = 5.0
FLEX_MAX_RETRY_DELAY_SECONDS = 60.0

_LOG = logging.getLogger(__name__)


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


def _capacity_retry_delay(error: RateLimitError, attempt: int) -> float | None:
    """Back off on capacity refusals, respecting bounded server retry guidance."""
    if error.code != "flex_unavailable" and not (
        error.code is None and error.type == "resource_unavailable"
    ):
        return None
    headers = error.response.headers
    if headers.get("x-should-retry", "").lower() == "false":
        return None

    server_delay = None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            parsed = float(value) * scale
        except ValueError:
            if name != "retry-after":
                continue
            try:
                parsed = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(parsed) and parsed > 0:
            server_delay = parsed
            break

    # Do not retry earlier than requested or sleep beyond this bounded policy.
    if server_delay is not None and server_delay > FLEX_MAX_RETRY_DELAY_SECONDS:
        return None
    backoff = min(
        FLEX_MAX_RETRY_DELAY_SECONDS,
        FLEX_INITIAL_RETRY_DELAY_SECONDS * (2 ** attempt),
    ) * random.uniform(0.8, 1.2)
    return max(
        server_delay or 0.0,
        min(backoff, FLEX_MAX_RETRY_DELAY_SECONDS),
    )


def create_openai_request(
    client: OpenAI,
    api_type: Literal["responses", "chat_completions"],
    kwargs: dict,
    *,
    allow_flex_retries: bool = True,
):
    """Add slower retries for refused Flex capacity, never a tier fallback.

    The first dispatch retains the SDK's existing retry behavior. After a known
    capacity refusal, additional attempts disable SDK retries so retry loops do
    not multiply. Other errors propagate; timeouts may have incurred charges.
    Workers opt out entirely to preserve their request/deadline budget contract.
    """
    retry_budget = (
        FLEX_MAX_CAPACITY_RETRIES
        if allow_flex_retries and kwargs.get("service_tier") == "flex"
        else 0
    )
    for attempt in range(retry_budget + 1):
        try:
            if api_type == "responses":
                response = client.responses.create(**kwargs)
            elif api_type == "chat_completions":
                response = client.chat.completions.create(**kwargs)
            else:
                raise ValueError(f"Unsupported OpenAI request API: {api_type}")
        except RateLimitError as error:
            if attempt >= retry_budget:
                raise
            delay = _capacity_retry_delay(error, attempt)
            if delay is None:
                raise
            if attempt == 0:
                client = client.with_options(max_retries=0)
            _LOG.warning(
                "Flex capacity unavailable; retrying in %.1fs (%d/%d), staying on Flex. "
                "request_id=%s",
                delay, attempt + 1, retry_budget, error.request_id,
            )
            time.sleep(delay)
        else:
            _LOG.debug(
                "OpenAI request completed: api=%s requested_tier=%s actual_tier=%s request_id=%s",
                api_type, kwargs.get("service_tier", "project_default"),
                getattr(response, "service_tier", None), getattr(response, "_request_id", None),
            )
            return response
    raise AssertionError("OpenAI request retry loop exhausted without a result or error")

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

from llm.base import REQUEST_RETRY_NOTE_PREFIX
from llm.request_progress import notify_request_retry

if TYPE_CHECKING:
    from runtime.state import ModelSettings


FLEX_REQUEST_TIMEOUT_SECONDS = 900.0
FLEX_MAX_CAPACITY_RETRIES = 5
FLEX_INITIAL_RETRY_DELAY_SECONDS = 5.0
FLEX_MAX_RETRY_DELAY_SECONDS = 60.0
FLEX_MAX_SERVER_RETRY_DELAY_SECONDS = 300.0
FLEX_MAX_EXTRA_BACKOFF_SECONDS = 300.0

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


def _server_retry_delay_seconds(error: RateLimitError) -> float | None:
    """Parse a positive finite server minimum without exposing raw headers."""
    headers = error.response.headers
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

    return server_delay


def _capacity_retry_decision(
    error: RateLimitError,
    attempt: int,
    remaining_backoff: float = FLEX_MAX_EXTRA_BACKOFF_SECONDS,
) -> tuple[float | None, str]:
    """Return a bounded delay or fixed stop label, never raw server text."""
    if error.code != "flex_unavailable" and not (
        error.code is None and error.type == "resource_unavailable"
    ):
        return None, "not_flex_capacity"
    if error.response.headers.get("x-should-retry", "").lower() == "false":
        return None, "server_x_should_retry_false"

    server_delay = _server_retry_delay_seconds(error)
    # The ordinary backoff cap is not a reason to discard a longer server
    # minimum. Honor that minimum in full, or stop at the separate hard bounds.
    if server_delay is not None and server_delay > FLEX_MAX_SERVER_RETRY_DELAY_SECONDS:
        return None, "server_retry_after_exceeds_300s"
    backoff = min(
        FLEX_MAX_RETRY_DELAY_SECONDS,
        FLEX_INITIAL_RETRY_DELAY_SECONDS * (2 ** attempt),
    ) * random.uniform(0.8, 1.2)
    delay = max(server_delay or 0.0, min(backoff, FLEX_MAX_RETRY_DELAY_SECONDS))
    if delay > remaining_backoff:
        return None, "extra_backoff_budget_exhausted"
    return delay, "retry"


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
    Ordinary backoff stays capped at 60s; server minimums may reach 300s, with
    at most 300s of extra sleep in total (not a total request deadline).
    """
    retry_budget = (
        FLEX_MAX_CAPACITY_RETRIES
        if allow_flex_retries and kwargs.get("service_tier") == "flex"
        else 0
    )
    started = time.monotonic()
    extra_backoff = 0.0
    for attempt in range(retry_budget + 1):
        try:
            if api_type == "responses":
                response = client.responses.create(**kwargs)
            elif api_type == "chat_completions":
                response = client.chat.completions.create(**kwargs)
            else:
                raise ValueError(f"Unsupported OpenAI request API: {api_type}")
        except RateLimitError as error:
            delay, stop_reason = _capacity_retry_decision(
                error, attempt, FLEX_MAX_EXTRA_BACKOFF_SECONDS - extra_backoff,
            )
            if stop_reason == "not_flex_capacity":
                raise
            if attempt >= retry_budget:
                delay = None
                if not allow_flex_retries:
                    stop_reason = "extra_retries_disabled"
                elif kwargs.get("service_tier") != "flex":
                    stop_reason = "flex_not_explicitly_requested"
                else:
                    stop_reason = "retry_budget_exhausted"
            if delay is None:
                # Preserve SDK exception type/identity and provider body. The
                # agent surfaces only this bounded note; no request content,
                # raw headers, credentials or arbitrary exception notes added.
                tier = "flex" if kwargs.get("service_tier") == "flex" else "not_explicit_flex"
                server_delay = _server_retry_delay_seconds(error)
                server_min = "none" if server_delay is None else f"{server_delay:.3g}s"
                diagnostic = (
                    REQUEST_RETRY_NOTE_PREFIX + "Flex capacity; "
                    f"extra_retries={attempt}/{retry_budget}; "
                    f"extra_backoff={extra_backoff:.1f}s; "
                    f"elapsed={max(0.0, time.monotonic() - started):.1f}s; "
                    f"stop={stop_reason}; requested_tier={tier}; server_min_wait={server_min}"
                )
                error.add_note(diagnostic)
                _LOG.warning("%s", diagnostic)
                raise
            if attempt == 0:
                client = client.with_options(max_retries=0)
            _LOG.warning(
                "Flex capacity unavailable; retrying in %.1fs (%d/%d), staying on Flex. "
                "request_id=%s",
                delay, attempt + 1, retry_budget, error.request_id,
            )
            notify_request_retry(delay, attempt + 1, retry_budget)
            time.sleep(delay)
            extra_backoff += delay
        else:
            _LOG.debug(
                "OpenAI request completed: api=%s requested_tier=%s actual_tier=%s request_id=%s",
                api_type, kwargs.get("service_tier", "project_default"),
                getattr(response, "service_tier", None), getattr(response, "_request_id", None),
            )
            return response
    raise AssertionError("OpenAI request retry loop exhausted without a result or error")

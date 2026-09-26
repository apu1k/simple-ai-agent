"""Host-only per-job provider binding from an administrator-owned registry.

IDs in the policy never select a Python module, endpoint or credential. The
single fixed provider factory is imported only inside the spawned host child;
this module does not load the head-agent runtime or its tool registry.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from importlib import import_module
from types import SimpleNamespace
from typing import Mapping

from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.inference import InferenceModel, LLMInferenceModel
from llm.worker_limits import WorkerRequestLimits

_DIRECT_OPENAI = frozenset({"https://api.openai.com/v1", "https://api.openai.com/v1/"})


@dataclass(frozen=True)
class ApprovedModelFactory:
    """Picklable host-only factory; each invocation makes a new client/state."""

    provider: object  # Trusted registry's frozen ProviderConfig (host-only secrets).
    model_id: str
    reasoning_effort: str | None
    flex: bool
    max_output_tokens: int
    deadline_monotonic: float

    @classmethod
    def bind(
        cls, policy: WorkerExecutionPolicy, approved: Mapping[str, object],
        *, deadline_monotonic: float,
    ) -> ApprovedModelFactory:
        if (type(deadline_monotonic) not in (float, int)
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic <= time.monotonic()):
            raise ValueError("job inference deadline must be a future monotonic timestamp")
        try:
            provider = approved[policy.provider_id]
        except KeyError as exc:
            raise ValueError("provider is not administrator-approved") from exc
        if (
            getattr(provider, "key", None) != policy.provider_id
            or getattr(provider, "default_model", None) != policy.model_id
        ):
            raise ValueError("model does not match the approved provider profile")
        if getattr(provider, "api_type", None) not in {"chat_completions", "responses"}:
            raise ValueError("worker model requires an approved native-tool API")
        # Do not silently drop an approved reasoning/Flex setting or fall back
        # to another tier when a gateway/OPENAI_BASE_URL redirects the SDK.
        if (policy.service_tier == "flex" or policy.reasoning_effort is not None) and (
            getattr(provider, "base_url", None) not in _DIRECT_OPENAI
        ):
            raise ValueError("Flex/reasoning requires an explicit reviewed direct OpenAI endpoint")
        return cls(
            provider=provider, model_id=policy.model_id,
            reasoning_effort=policy.reasoning_effort,
            flex=policy.service_tier == "flex",
            max_output_tokens=policy.budget.max_output_tokens,
            deadline_monotonic=deadline_monotonic,
        )

    def __call__(self) -> InferenceModel:
        # This import is fixed by trusted code, never selected by task/model text.
        # The SDK and response continuation state are created inside the child.
        create_client = import_module("llm.providers").create_llm_client
        client = create_client(self.provider, self.model_id)
        if (self.flex or self.reasoning_effort is not None) and (
            str(getattr(client, "_base_url", "")).rstrip("/") != "https://api.openai.com/v1"
        ):
            raise ValueError("worker client did not resolve to the reviewed direct endpoint")
        client.configure_worker_limits(WorkerRequestLimits(
            self.max_output_tokens, self.deadline_monotonic,
        ))
        client.configure_model_settings(SimpleNamespace(
            openai_flex=self.flex,
            openai_reasoning_effort=self.reasoning_effort,
        ))
        return LLMInferenceModel(client)

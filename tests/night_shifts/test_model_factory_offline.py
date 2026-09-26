"""Trusted provider binding and per-job settings without a network call."""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError

import pytest

from llm.providers import ProviderConfig
from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.model_factory import ApprovedModelFactory
from night_shifts.models import AgentPlan, JobBudget, NightShiftJob


def _policy(*, model: str = "approved", tier: str = "default") -> WorkerExecutionPolicy:
    return WorkerExecutionPolicy.snapshot(
        NightShiftJob(
            "fixture", "work", "coding-worker", repository_id="fixture",
            starting_revision="a" * 40, plan=AgentPlan.FLEX, budget=JobBudget(),
        ),
        image_sha256="f" * 64, model_id=model, provider_id="trusted",
        reasoning_effort="low", service_tier=tier,
    )


def _provider(*, model: str = "approved", base_url: str | None = "https://api.openai.com/v1") -> ProviderConfig:
    return ProviderConfig(
        key="trusted", label="Trusted", api_key="fake-key", base_url=base_url,
        api_type="responses", default_model=model, supports_model_listing=False,
    )


def _bind(policy, providers):
    return ApprovedModelFactory.bind(
        policy, providers, deadline_monotonic=time.monotonic() + 15,
    )


def test_per_job_provider_clients_get_immutable_settings_without_head_preferences(monkeypatch) -> None:
    clients = []

    class FakeClient:
        supports_native_tools = True
        api_type = "responses"
        _base_url = "https://api.openai.com/v1/"

        def configure_worker_limits(self, limits) -> None:
            self.limits = limits

        def configure_model_settings(self, settings) -> None:
            self.settings = settings

    def make_client(provider, model):
        assert provider.key == "trusted" and model == "approved"
        instance = FakeClient()
        clients.append(instance)
        return instance

    monkeypatch.setattr("llm.providers.create_llm_client", make_client)
    binding = _bind(_policy(tier="flex"), {"trusted": _provider()})
    first, second = binding(), binding()
    assert first is not second
    assert first._client is clients[0] and second._client is clients[1]
    assert clients[0].settings is not clients[1].settings
    assert clients[0].settings.openai_flex is True
    assert clients[0].settings.openai_reasoning_effort == "low"
    assert clients[0].limits.max_output_tokens == 4096
    assert clients[0].limits is not clients[1].limits
    with pytest.raises(FrozenInstanceError):
        binding.model_id = "unapproved"  # type: ignore[misc]


def test_unapproved_model_provider_and_flex_endpoint_are_rejected_before_creation() -> None:
    with pytest.raises(ValueError, match="not administrator-approved"):
        _bind(_policy(), {})
    with pytest.raises(ValueError, match="model does not match"):
        _bind(_policy(model="changed"), {"trusted": _provider()})
    with pytest.raises(ValueError, match="endpoint"):
        _bind(_policy(tier="flex"), {"trusted": _provider(base_url="http://other.invalid/v1")})
    with pytest.raises(ValueError, match="endpoint"):
        _bind(_policy(tier="flex"), {"trusted": _provider(base_url=None)})
    with pytest.raises(ValueError, match="endpoint"):
        _bind(_policy(), {"trusted": _provider(base_url="https://compatible.invalid/v1")})

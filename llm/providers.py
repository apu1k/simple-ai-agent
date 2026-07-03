"""
llm/providers.py

Loads provider configs from providers.toml and creates LLM clients.

To add a new provider type:
  1. Create llm/myprovider.py implementing LLMClient
  2. Add its api_type string to the factory in create_llm_client()
"""

import os
import tomllib
from dataclasses import dataclass
from typing import Literal

from config.settings import PROVIDERS_EXAMPLE_FILE, PROVIDERS_FILE


ApiType = Literal["chat_completions", "responses", "completions"]


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    label: str
    api_key: str | None
    base_url: str | None
    api_type: ApiType
    default_model: str
    supports_model_listing: bool
    api_key_envs: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# LLM client factory
# ---------------------------------------------------------------------------

def create_llm_client(provider: ProviderConfig, model: str):
    """
    Create the right LLM client for a given provider config and model.
    Returns an object implementing llm/base.py LLMClient.
    """
    # Build a temporary config with the selected model
    effective = ProviderConfig(
        key=provider.key,
        label=provider.label,
        api_key=provider.api_key,
        base_url=provider.base_url,
        api_type=provider.api_type,
        default_model=model,
        supports_model_listing=provider.supports_model_listing,
        api_key_envs=provider.api_key_envs,
    )

    # IMPORTANT: branch on effective.api_type (the normalized runtime config),
    # not the original provider object.
    if effective.api_type == "chat_completions":
        from llm.openai_chat import OpenAIChatClient
        return OpenAIChatClient(effective)

    if effective.api_type == "responses":
        from llm.openai_responses import OpenAIResponsesClient
        return OpenAIResponsesClient(effective)

    if effective.api_type == "completions":
        from llm.openai_completions import OpenAICompletionsClient
        return OpenAICompletionsClient(effective)

    raise ValueError(f"Unsupported api_type: '{effective.api_type}'")


# Debug helper - remove after testing
def _debug_provider_config():
    """Print loaded provider configs for debugging."""
    import sys
    print("=== LOADED PROVIDERS ===", file=sys.stderr)
    for key, p in PROVIDERS.items():
        print(f"  {key}: api_type={p.api_type}, model={p.default_model}", file=sys.stderr)
    print("========================", file=sys.stderr)


# ---------------------------------------------------------------------------
# Model listing and selection (interactive CLI)
# ---------------------------------------------------------------------------

def list_provider_models(
    provider: ProviderConfig,
    *,
    timeout: float = 6.0,
    max_retries: int = 0,
) -> list[str]:
    if not provider.supports_model_listing:
        return []
    try:
        from openai import OpenAI

        kwargs = {
            "api_key": provider.api_key,
            "timeout": timeout,
            "max_retries": max_retries,
        }
        if provider.base_url:
            kwargs["base_url"] = provider.base_url

        client = OpenAI(**kwargs)
        return sorted(m.id for m in client.models.list().data)
    except Exception as e:
        print(f"Warning: Could not fetch models for {provider.label}: {e}")
        return []


def _choose_from_list(title: str, items: list[str]) -> str:
    print()
    print(title)
    for i, item in enumerate(items, start=1):
        print(f"[{i}] {item}")
    while True:
        choice = input("Choose an option: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        print("Invalid choice.")


def choose_provider(providers: dict[str, ProviderConfig]) -> ProviderConfig:
    if not providers:
        raise ValueError("No providers configured.")
    items = list(providers.values())
    labels = [p.label for p in items]
    selected_label = _choose_from_list("Choose provider:", labels)
    return items[labels.index(selected_label)]


def choose_model(provider: ProviderConfig) -> str:
    all_models = list_provider_models(provider)
    filter_text = input("Filter models? Leave empty for all: ").strip()
    models = (
        [m for m in all_models if filter_text.lower() in m.lower()] or all_models
        if filter_text else all_models
    )

    print()
    print(f"Choose model for {provider.label}:")
    if provider.default_model:
        print(f"[0] Use default: {provider.default_model}")
    for i, m in enumerate(models, start=1):
        marker = " (default)" if m == provider.default_model else ""
        print(f"[{i}] {m}{marker}")
    print("[m] Enter model ID manually")

    if not models and not provider.default_model:
        model = input("No models available. Enter model ID manually: ").strip()
        if not model:
            raise ValueError("No model selected.")
        return model

    while True:
        choice = input("Choose model: ").strip()
        if provider.default_model and choice == "0":
            return provider.default_model
        if choice.lower() in {"m", "manual"}:
            model = input("Enter model ID manually: ").strip()
            if model:
                return model
            print("No model entered.")
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]
        print("Invalid choice.")


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

def _required_str(data: dict, field: str, index: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Provider #{index} missing required field: '{field}'")
    return value.strip()


def _optional_str(data: dict, field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Optional field '{field}' must be a string.")
    return value.strip() or None


def _env_names(data: dict, singular: str, plural: str) -> tuple[str, ...]:
    names = []
    for key in (singular, plural):
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            if val.strip():
                names.append(val.strip())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
        else:
            raise ValueError(f"Field '{key}' must be a string or list of strings.")
    return tuple(dict.fromkeys(names))


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        val = os.getenv(name)
        if val:
            return val
    return None


def _build_provider(data: dict, index: int) -> ProviderConfig:
    if not isinstance(data, dict):
        raise ValueError(f"Provider #{index} must be a TOML table.")

    key = _required_str(data, "key", index)
    label = _required_str(data, "label", index)
    api_type_raw = _required_str(data, "api_type", index)
    if api_type_raw not in {"chat_completions", "responses", "completions"}:
        raise ValueError(f"Provider #{index} has invalid api_type: '{api_type_raw}'")
    api_type: ApiType = api_type_raw  # type: ignore

    api_key_envs = _env_names(data, "api_key_env", "api_key_envs")
    base_url_envs = _env_names(data, "base_url_env", "base_url_envs")
    model_envs = _env_names(data, "default_model_env", "default_model_envs")

    api_key = _optional_str(data, "api_key") or _first_env(api_key_envs)
    base_url = _first_env(base_url_envs) or _optional_str(data, "base_url")
    default_model = _first_env(model_envs) or _optional_str(data, "default_model") or ""

    supports_listing = data.get("supports_model_listing", True)
    if not isinstance(supports_listing, bool):
        raise ValueError(f"Provider #{index} 'supports_model_listing' must be true or false.")

    return ProviderConfig(
        key=key,
        label=label,
        api_key=api_key,
        base_url=base_url,
        api_type=api_type,
        default_model=default_model,
        supports_model_listing=supports_listing,
        api_key_envs=api_key_envs,
    )


def load_providers() -> dict[str, ProviderConfig]:
    if PROVIDERS_FILE.exists():
        path = PROVIDERS_FILE
    elif PROVIDERS_EXAMPLE_FILE.exists():
        path = PROVIDERS_EXAMPLE_FILE
    else:
        raise FileNotFoundError(
            "No provider configuration found. "
            "Create providers.toml or providers.example.toml."
        )

    with path.open("rb") as f:
        try:
            config = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Invalid TOML in {path}: {e}") from e

    providers_data = config.get("providers")
    if not isinstance(providers_data, list):
        raise ValueError(f"{path} must contain at least one [[providers]] table.")

    providers: dict[str, ProviderConfig] = {}
    for i, pdata in enumerate(providers_data, start=1):
        p = _build_provider(pdata, i)
        if p.key in providers:
            raise ValueError(f"Duplicate provider key: '{p.key}'")
        providers[p.key] = p

    if not providers:
        raise ValueError(f"No providers configured in {path}.")

    return providers


# Loaded once at import time
PROVIDERS = load_providers()

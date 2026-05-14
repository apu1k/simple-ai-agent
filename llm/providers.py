import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from config import PROVIDERS_EXAMPLE_FILE, PROVIDERS_FILE

ApiType = Literal["chat_completions", "responses"]


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


def _required_string(data, field_name, provider_index):
    value = data.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Provider #{provider_index} is missing required string field: {field_name}"
        )

    return value.strip()


def _optional_string(data, field_name):
    value = data.get(field_name)

    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(f"Optional field '{field_name}' must be a string if set.")

    value = value.strip()
    return value or None


def _normalize_env_names(value, field_name):
    if value is None:
        return ()

    if isinstance(value, str):
        value = value.strip()
        return (value,) if value else ()

    if isinstance(value, list):
        env_names = []

        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Field '{field_name}' must contain only non-empty strings."
                )

            env_names.append(item.strip())

        return tuple(env_names)

    raise ValueError(
        f"Field '{field_name}' must be either a string or a list of strings."
    )


def _get_env_names(data, singular_name, plural_name):
    env_names = []

    singular_value = data.get(singular_name)
    plural_value = data.get(plural_name)

    env_names.extend(_normalize_env_names(singular_value, singular_name))
    env_names.extend(_normalize_env_names(plural_value, plural_name))

    return tuple(dict.fromkeys(env_names))


def _resolve_first_env_value(env_names):
    for env_name in env_names:
        value = os.getenv(env_name)

        if value:
            return value

    return None


def _validate_api_type(api_type):
    allowed_api_types = {"chat_completions", "responses"}

    if api_type not in allowed_api_types:
        raise ValueError(
            f"Invalid api_type '{api_type}'. "
            f"Allowed values: {sorted(allowed_api_types)}"
        )

    return api_type


def _get_supports_model_listing(data):
    value = data.get("supports_model_listing", True)

    if not isinstance(value, bool):
        raise ValueError("Field 'supports_model_listing' must be true or false.")

    return value


def _select_provider_file():
    if PROVIDERS_FILE.exists():
        return PROVIDERS_FILE

    if PROVIDERS_EXAMPLE_FILE.exists():
        return PROVIDERS_EXAMPLE_FILE

    raise FileNotFoundError(
        "No provider configuration found. "
        "Create providers.toml or add providers.example.toml."
    )


def _load_toml_file(path: Path):
    with path.open("rb") as file:
        return tomllib.load(file)


def _build_provider(provider_data, provider_index):
    if not isinstance(provider_data, dict):
        raise ValueError(f"Provider #{provider_index} must be a TOML table.")

    key = _required_string(provider_data, "key", provider_index)
    label = _required_string(provider_data, "label", provider_index)
    api_type = _validate_api_type(
        _required_string(provider_data, "api_type", provider_index)
    )

    api_key_envs = _get_env_names(
        provider_data,
        singular_name="api_key_env",
        plural_name="api_key_envs",
    )
    base_url_envs = _get_env_names(
        provider_data,
        singular_name="base_url_env",
        plural_name="base_url_envs",
    )
    default_model_envs = _get_env_names(
        provider_data,
        singular_name="default_model_env",
        plural_name="default_model_envs",
    )

    api_key = _optional_string(provider_data, "api_key")
    if api_key is None:
        api_key = _resolve_first_env_value(api_key_envs)

    base_url = _resolve_first_env_value(base_url_envs)
    if base_url is None:
        base_url = _optional_string(provider_data, "base_url")

    default_model = _resolve_first_env_value(default_model_envs)
    if default_model is None:
        default_model = _optional_string(provider_data, "default_model") or ""

    supports_model_listing = _get_supports_model_listing(provider_data)

    return ProviderConfig(
        key=key,
        label=label,
        api_key=api_key,
        base_url=base_url,
        api_type=api_type,
        default_model=default_model,
        supports_model_listing=supports_model_listing,
        api_key_envs=api_key_envs,
    )


def load_providers():
    provider_file = _select_provider_file()

    try:
        config_data = _load_toml_file(provider_file)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid TOML in {provider_file}: {e}") from e

    providers_data = config_data.get("providers")

    if not isinstance(providers_data, list):
        raise ValueError(
            f"{provider_file} must contain at least one [[providers]] table."
        )

    providers = {}

    for index, provider_data in enumerate(providers_data, start=1):
        provider = _build_provider(provider_data, index)

        if provider.key in providers:
            raise ValueError(
                f"Duplicate provider key in {provider_file}: {provider.key}"
            )

        providers[provider.key] = provider

    if not providers:
        raise ValueError(f"No providers configured in {provider_file}.")

    return providers


PROVIDERS = load_providers()
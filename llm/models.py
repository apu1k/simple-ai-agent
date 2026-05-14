from dataclasses import dataclass

from openai import OpenAI

from llm.providers import PROVIDERS, ProviderConfig


@dataclass(frozen=True)
class ModelConfig:
    provider_key: str
    provider_label: str
    model: str
    api_key: str
    base_url: str | None
    api_type: str


def create_openai_client(provider: ProviderConfig):
    if not provider.api_key:
        raise ValueError(_missing_api_key_message(provider))

    if provider.base_url:
        return OpenAI(
            api_key=provider.api_key,
            base_url=provider.base_url,
        )

    return OpenAI(api_key=provider.api_key)


def _missing_api_key_message(provider: ProviderConfig):
    if provider.api_key_envs:
        return (
            f"Missing API key for provider: {provider.label}. "
            f"Set one of these environment variables: "
            f"{', '.join(provider.api_key_envs)}"
        )

    return (
        f"Missing API key for provider: {provider.label}. "
        "Set api_key_env/api_key_envs in providers.toml and define the variable in .env."
    )


def list_provider_models(provider: ProviderConfig):
    if not provider.supports_model_listing:
        return []

    try:
        client = create_openai_client(provider)
        models_response = client.models.list()
        model_ids = sorted([model.id for model in models_response.data])
        return model_ids
    except Exception as e:
        print(f"Warning: Could not fetch models for {provider.label}: {e}")
        return []


def choose_from_list(title, items):
    print()
    print(title)

    for index, item in enumerate(items, start=1):
        print(f"[{index}] {item}")

    while True:
        choice = input("Choose an option: ").strip()

        if not choice.isdigit():
            print("Please enter a number.")
            continue

        index = int(choice)

        if 1 <= index <= len(items):
            return items[index - 1]

        print("Invalid choice.")


def choose_provider():
    if not PROVIDERS:
        raise ValueError("No providers configured.")

    provider_items = list(PROVIDERS.values())
    labels = [provider.label for provider in provider_items]

    selected_label = choose_from_list("Choose provider:", labels)
    selected_index = labels.index(selected_label)

    return provider_items[selected_index]


def filter_models(models):
    if not models:
        return []

    filter_text = input("Filter models? Leave empty for all: ").strip()

    if not filter_text:
        return models

    filtered_models = [
        model for model in models
        if filter_text.lower() in model.lower()
    ]

    if not filtered_models:
        print(f"No models matched '{filter_text}'. Showing all models.")
        return models

    return filtered_models


def choose_model(provider: ProviderConfig):
    all_models = list_provider_models(provider)
    models = filter_models(all_models)

    print()
    print(f"Choose model for {provider.label}:")

    if provider.default_model:
        print(f"[0] Use default: {provider.default_model}")

    for index, model in enumerate(models, start=1):
        marker = " (default)" if model == provider.default_model else ""
        print(f"[{index}] {model}{marker}")

    print("[m] Enter model ID manually")

    if not models and not provider.default_model:
        manual_model = input(
            f"No models could be fetched for {provider.label}. "
            "Enter model ID manually: "
        ).strip()

        if not manual_model:
            raise ValueError("No model selected.")

        return manual_model

    while True:
        choice = input("Choose model: ").strip()

        if provider.default_model and choice == "0":
            return provider.default_model

        if choice.lower() in {"m", "manual"}:
            manual_model = input("Enter model ID manually: ").strip()

            if manual_model:
                return manual_model

            print("No model entered.")
            continue

        if not choice.isdigit():
            print("Please enter a number, 0 for default, or 'm' for manual model ID.")
            continue

        index = int(choice)

        if 1 <= index <= len(models):
            return models[index - 1]

        print("Invalid choice.")


def select_model_config():
    provider = choose_provider()
    model = choose_model(provider)

    if not provider.api_key:
        raise ValueError(_missing_api_key_message(provider))

    return ModelConfig(
        provider_key=provider.key,
        provider_label=provider.label,
        model=model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        api_type=provider.api_type,
    )
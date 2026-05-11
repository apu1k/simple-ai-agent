from dataclasses import dataclass
from typing import Literal

from config import (
    GWDG_API_KEY,
    GWDG_BASE_URL,
    GWDG_DEFAULT_MODEL,
    UPB_API_KEY,
    UPB_BASE_URL,
    UPB_DEFAULT_MODEL,
    OPENAI_PERSONAL_API_KEY,
    OPENAI_PERSONAL_DEFAULT_MODEL,
)


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


PROVIDERS = {
    "gwdg": ProviderConfig(
        key="gwdg",
        label="GWDG",
        api_key=GWDG_API_KEY,
        base_url=GWDG_BASE_URL,
        api_type="chat_completions",
        default_model=GWDG_DEFAULT_MODEL,
        supports_model_listing=True,
    ),
    "upb": ProviderConfig(
        key="upb",
        label="UPB AI Gateway",
        api_key=UPB_API_KEY,
        base_url=UPB_BASE_URL,
        api_type="chat_completions",
        default_model=UPB_DEFAULT_MODEL,
        supports_model_listing=True,
    ),
    "openai_personal": ProviderConfig(
        key="openai_personal",
        label="Personal OpenAI",
        api_key=OPENAI_PERSONAL_API_KEY,
        base_url=None,
        api_type="responses",
        default_model=OPENAI_PERSONAL_DEFAULT_MODEL,
        supports_model_listing=True,
    ),
}
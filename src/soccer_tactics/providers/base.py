"""Model provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str = Field(min_length=1)
    base_url: str
    api_key: SecretStr | None = Field(default=None, repr=False)
    reasoning_effort: str | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def validate_endpoint(self) -> ModelConfiguration:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) endpoint")
        return self

    @property
    def model_id(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ProviderCapabilities:
    api_mode: Literal["native", "chat_completions", "responses"]
    structured_output: bool
    reasoning_effort: bool = False


@dataclass(frozen=True)
class ProviderModel:
    chat_model: Any
    authentication: str
    capabilities: ProviderCapabilities


class ProviderAdapter(Protocol):
    provider_id: str
    display_name: str
    capabilities: ProviderCapabilities

    def validate(self, configuration: ModelConfiguration) -> None: ...

    def build(self, configuration: ModelConfiguration) -> ProviderModel: ...

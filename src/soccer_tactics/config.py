"""Application settings and local storage paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: user_data_path("soccer-tactics-agent", ensure_exists=True))
    model_provider: str = "azure_foundry"
    model: str = "gpt-5-mini"
    foundry_endpoint: str = ""
    foundry_api_key: SecretStr | None = Field(default=None, repr=False)
    reasoning_effort: str | None = "medium"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    log_level: str = "INFO"

    @field_validator("model_provider", "log_level", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str:
        return str(value).strip().lower()

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_directories(self) -> None:
        for path in (self.raw_dir, self.processed_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings

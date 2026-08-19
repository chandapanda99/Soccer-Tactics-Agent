from __future__ import annotations

from soccer_tactics.config import Settings


def test_settings_use_unprefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test:latest")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.model_provider == "ollama"
    assert settings.ollama_model == "qwen-test:latest"
    assert settings.log_level == "debug"

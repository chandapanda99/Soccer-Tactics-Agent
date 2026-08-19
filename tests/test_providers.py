from __future__ import annotations

import pytest
from pydantic import SecretStr

from soccer_tactics.providers import ModelConfiguration, get_provider, provider_choices


def test_builtin_providers_are_registered():
    assert {provider for provider, _ in provider_choices()} == {"azure_foundry", "ollama"}


def test_foundry_requires_https_v1_endpoint():
    provider = get_provider("azure_foundry")
    with pytest.raises(ValueError, match="HTTPS"):
        provider.validate(ModelConfiguration(provider="azure_foundry", model="x", base_url="http://example.com/openai/v1/"))
    with pytest.raises(ValueError, match="openai/v1"):
        provider.validate(ModelConfiguration(provider="azure_foundry", model="x", base_url="https://example.com/"))


def test_foundry_and_ollama_build_through_the_same_contract(monkeypatch):
    import langchain_ollama
    import langchain_openai

    created = []

    class DummyModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.use_responses_api = kwargs.get("use_responses_api")
            created.append(kwargs)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", DummyModel)
    foundry = get_provider("azure_foundry").build(
        ModelConfiguration(
            provider="azure_foundry",
            model="deployment",
            base_url="https://example.openai.azure.com/openai/v1/",
            api_key=SecretStr("test-key"),
            reasoning_effort="medium",
        )
    )
    assert foundry.authentication == "api_key"
    assert foundry.capabilities.api_mode == "responses"
    assert created[-1]["use_responses_api"] is True
    assert created[-1]["reasoning"] == {"effort": "medium"}

    monkeypatch.setattr(langchain_ollama, "ChatOllama", DummyModel)
    ollama = get_provider("ollama").build(ModelConfiguration(provider="ollama", model="local-model", base_url="http://127.0.0.1:11434"))
    assert ollama.authentication == "local"
    assert created[-1]["model"] == "local-model"


def test_foundry_fails_if_responses_api_is_not_active(monkeypatch):
    import langchain_openai

    class NonResponsesModel:
        use_responses_api = False

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", NonResponsesModel)

    with pytest.raises(RuntimeError, match="must use OpenAI's Responses API"):
        get_provider("azure_foundry").build(
            ModelConfiguration(
                provider="azure_foundry",
                model="deployment",
                base_url="https://example.openai.azure.com/openai/v1/",
                api_key=SecretStr("test-key"),
            )
        )

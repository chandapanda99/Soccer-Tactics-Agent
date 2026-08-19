"""Local Ollama adapter."""

from __future__ import annotations

from urllib.parse import urlparse

from soccer_tactics.providers.base import ModelConfiguration, ProviderCapabilities, ProviderModel


class OllamaProvider:
    provider_id = "ollama"
    display_name = "Ollama"
    capabilities = ProviderCapabilities(api_mode="native", structured_output=True)

    def validate(self, configuration: ModelConfiguration) -> None:
        endpoint = urlparse(configuration.base_url)
        if endpoint.scheme not in {"http", "https"}:
            raise ValueError("Ollama base_url must use HTTP(S)")
        if configuration.reasoning_effort:
            raise ValueError("Ollama adapter does not accept reasoning_effort")

    def build(self, configuration: ModelConfiguration) -> ProviderModel:
        from langchain_ollama import ChatOllama

        self.validate(configuration)
        model = ChatOllama(model=configuration.model, base_url=configuration.base_url, **configuration.provider_options)
        return ProviderModel(model, "local", self.capabilities)

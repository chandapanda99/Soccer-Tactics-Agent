"""Azure Foundry OpenAI-compatible Responses API adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from soccer_tactics.providers.base import ModelConfiguration, ProviderCapabilities, ProviderModel


class AzureFoundryProvider:
    provider_id = "azure_foundry"
    display_name = "Azure Foundry"
    capabilities = ProviderCapabilities(api_mode="responses", structured_output=True, reasoning_effort=True)

    def validate(self, configuration: ModelConfiguration) -> None:
        endpoint = urlparse(configuration.base_url)
        if endpoint.scheme != "https":
            raise ValueError("Azure Foundry endpoints must use HTTPS")
        if not endpoint.path.rstrip("/").endswith("/openai/v1"):
            raise ValueError("Azure Foundry base_url must end with /openai/v1/")

    def build(self, configuration: ModelConfiguration) -> ProviderModel:
        from langchain_openai import ChatOpenAI

        self.validate(configuration)
        api_key = configuration.api_key.get_secret_value() if configuration.api_key else None
        authentication = "api_key"
        credential: Any = api_key
        if not credential:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            authentication = "default_azure_credential"
        options: dict[str, Any] = dict(configuration.provider_options)
        if configuration.reasoning_effort:
            options["reasoning"] = {"effort": configuration.reasoning_effort}
        model = ChatOpenAI(
            model=configuration.model,
            base_url=configuration.base_url,
            api_key=credential,
            use_responses_api=True,
            **options,
        )
        if not getattr(model, "use_responses_api", None):
            raise RuntimeError("Azure Foundry models must use OpenAI's Responses API")
        return ProviderModel(model, authentication, self.capabilities)

"""Provider-neutral LangChain model registry."""

from soccer_tactics.providers.base import ModelConfiguration, ProviderCapabilities, ProviderModel
from soccer_tactics.providers.registry import get_provider, provider_choices, register_provider


def register_builtin_providers() -> None:
    from soccer_tactics.providers.azure_foundry import AzureFoundryProvider
    from soccer_tactics.providers.ollama import OllamaProvider

    register_provider(AzureFoundryProvider())
    register_provider(OllamaProvider())


register_builtin_providers()

__all__ = [
    "ModelConfiguration",
    "ProviderCapabilities",
    "ProviderModel",
    "get_provider",
    "provider_choices",
    "register_provider",
]

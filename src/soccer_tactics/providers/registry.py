"""Extensible provider registry."""

from soccer_tactics.providers.base import ProviderAdapter

_PROVIDERS: dict[str, ProviderAdapter] = {}


def register_provider(adapter: ProviderAdapter) -> None:
    _PROVIDERS[adapter.provider_id] = adapter


def get_provider(provider_id: str) -> ProviderAdapter:
    try:
        return _PROVIDERS[provider_id]
    except KeyError as error:
        raise ValueError(f"unsupported provider {provider_id!r}; registered providers: {sorted(_PROVIDERS)}") from error


def provider_choices() -> list[tuple[str, str]]:
    return [(provider_id, adapter.display_name) for provider_id, adapter in _PROVIDERS.items()]

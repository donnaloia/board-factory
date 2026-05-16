"""Instantiate the configured token provider."""

from __future__ import annotations

from .base import TokenProvider
from .mock import MockTokenProvider
from .openai import OpenAITokenProvider


def select_provider(provider_name: str, *, openai_key: str | None = None) -> TokenProvider:
    if provider_name == "mock":
        return MockTokenProvider()
    if provider_name == "openai":
        if not openai_key:
            raise RuntimeError(
                "Token Factory OpenAI provider requires an API key. "
                "Save it in Account → Connections → OpenAI / ChatGPT."
            )
        return OpenAITokenProvider(api_key=openai_key)
    raise ValueError(f"Unknown TOKENFACTORY_PROVIDER: {provider_name!r}")

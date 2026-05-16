"""Provider factory for Card Factory."""

from __future__ import annotations

from .base import CardProvider


def select_provider(name: str, *, openai_key: str | None = None) -> CardProvider:
    """Return the configured provider.

    ``name`` comes from ``config.provider_name()``; ``openai_key`` is the
    user's OpenAI API key (required when name == ``"openai"``).

    Raises ``RuntimeError`` for unknown names or missing required keys.
    """
    n = name.lower()
    if n == "mock":
        from .mock import MockCardProvider
        return MockCardProvider()
    if n == "openai":
        if not openai_key:
            raise RuntimeError(
                "OpenAI provider selected but no API key supplied. "
                "The user must configure their ChatGPT / OpenAI key in Account → Connections."
            )
        from .openai import OpenAICardProvider
        return OpenAICardProvider(openai_key)
    raise RuntimeError(
        f"Unknown CARD_FACTORY_PROVIDER {name!r}. Supported: 'openai', 'mock'."
    )

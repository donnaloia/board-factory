"""Factory: select a PixelArtProvider at runtime based on environment + settings.

The web app passes the per-board `generation` block (a `GenerationSpec`) through
to `get_provider`, so the chosen model / quality / preset travel with the board
rather than being baked into env vars.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .base import PixelArtProvider

if TYPE_CHECKING:
    from ..schemas.catalog import GenerationSpec


def get_provider(
    name: str | None = None,
    *,
    settings: "GenerationSpec | None" = None,
    pixellab_api_key: str | None = None,
    openai_api_key: str | None = None,
) -> PixelArtProvider:
    """Construct the provider matching ``name`` (or ``settings.provider``).

    API keys can be passed explicitly via ``pixellab_api_key`` /
    ``openai_api_key``; when ``None``, the providers fall back to the
    matching environment variables. This is the seam that lets the web
    layer stop mutating ``os.environ`` per request.
    """
    if name is None and settings is not None:
        name = settings.provider
    resolved = (name or os.environ.get("BOARDFACTORY_PROVIDER", "pixellab")).lower()

    if resolved == "pixellab":
        from .pixel.pixellab import PixelLabProvider
        kwargs: dict[str, Any] = {}
        if settings is not None:
            kwargs["preset"] = settings.pixellab.model
        if pixellab_api_key:
            kwargs["api_key"] = pixellab_api_key
        return PixelLabProvider(**kwargs)

    if resolved == "openai":
        from .openai_img import OpenAIImageProvider
        kwargs = {}
        if settings is not None:
            kwargs["model"] = settings.openai.model
            kwargs["quality"] = settings.openai.quality
        if openai_api_key:
            kwargs["api_key"] = openai_api_key
        return OpenAIImageProvider(**kwargs)

    if resolved == "mock":
        from .pixel.mock import MockProvider
        return MockProvider()

    raise ValueError(
        f"Unknown provider {resolved!r}. "
        f"Set BOARDFACTORY_PROVIDER to 'pixellab', 'openai', or 'mock'."
    )

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
) -> PixelArtProvider:
    """Construct the provider matching `name` (or `settings.provider`)."""
    if name is None and settings is not None:
        name = settings.provider
    resolved = (name or os.environ.get("BOARDFACTORY_PROVIDER", "pixellab")).lower()

    if resolved == "pixellab":
        from .pixel.pixellab import PixelLabProvider
        kwargs: dict[str, Any] = {}
        if settings is not None:
            kwargs["preset"] = settings.pixellab.model
        return PixelLabProvider(**kwargs)

    if resolved == "openai":
        from .openai_img import OpenAIImageProvider
        kwargs = {}
        if settings is not None:
            kwargs["model"] = settings.openai.model
            kwargs["quality"] = settings.openai.quality
        return OpenAIImageProvider(**kwargs)

    if resolved == "mock":
        from .pixel.mock import MockProvider
        return MockProvider()

    raise ValueError(
        f"Unknown provider {resolved!r}. "
        f"Set BOARDFACTORY_PROVIDER to 'pixellab', 'openai', or 'mock'."
    )

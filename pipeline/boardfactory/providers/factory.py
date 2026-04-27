"""Factory: select a PixelArtProvider at runtime based on environment."""

from __future__ import annotations

import os

from .base import PixelArtProvider


def get_provider(name: str | None = None) -> PixelArtProvider:
    name = (name or os.environ.get("BOARDFACTORY_PROVIDER", "pixellab")).lower()
    if name == "pixellab":
        from .pixel.pixellab import PixelLabProvider
        return PixelLabProvider()
    if name == "mock":
        from .pixel.mock import MockProvider
        return MockProvider()
    raise ValueError(
        f"Unknown provider {name!r}. Set BOARDFACTORY_PROVIDER to 'pixellab' or 'mock'."
    )

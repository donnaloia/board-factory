"""Abstract pixel-art provider interface.

Three operations a pixel art provider must support:
- generate: text-to-image (with optional style reference)
- img2img: image-to-image translation (preserve composition, restyle)
- inpaint: regenerate masked region of an image while preserving the rest

The pipeline talks to providers exclusively through this interface so swapping
PixelLab for local SDXL or a different hosted service is one new file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PixelArtProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        size: tuple[int, int],
        n: int = 1,
        style_reference: bytes | None = None,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        """Text-to-image generation. Returns N PNG byte blobs."""

    @abstractmethod
    def img2img(
        self,
        prompt: str,
        source_image: bytes,
        size: tuple[int, int],
        strength: float = 0.75,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        """Image-to-image translation. `strength` 0.0=preserve source, 1.0=fully restyle."""

    @abstractmethod
    def inpaint(
        self,
        prompt: str,
        source_image: bytes,
        mask_image: bytes,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        """Regenerate masked region only. White pixels in mask = regenerate, black = preserve."""

    def cost_estimate(self, size: tuple[int, int], n: int) -> float:
        """Estimated USD cost for the given call. Free providers return 0."""
        return 0.0

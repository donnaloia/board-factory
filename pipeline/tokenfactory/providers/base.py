"""Board Tokens provider protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image


class TokenProvider(Protocol):
    """Generate images for the token pipeline.

    All methods return a PIL ``Image`` (RGBA, ``canvas_w × canvas_h``).
    """

    def generate_candidate(
        self,
        *,
        canvas: tuple[int, int],
        prompt: str,
    ) -> Image.Image:
        """Generate one design-reference candidate (text-to-image)."""
        ...

    def generate_key_pose(
        self,
        *,
        canvas: tuple[int, int],
        reference_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        """Generate one animation key-pose frame (img2img from reference)."""
        ...

    def generate_interframe(
        self,
        *,
        canvas: tuple[int, int],
        source_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        """Generate one inter-frame from an alpha-blended source (img2img, high structure lock)."""
        ...

    def cost_estimate_usd(self, *, n_candidates: int, n_frames: int) -> float:
        """Return estimated cost in USD for a full session."""
        ...

"""Mock token provider — deterministic pixel art stand-ins for tests."""

from __future__ import annotations

import random

from PIL import Image, ImageDraw


class MockTokenProvider:
    """Generates solid-colour placeholder images with a simple silhouette.

    Uses a seeded RNG so the same prompt always returns the same colours,
    making test assertions predictable.
    """

    def generate_candidate(
        self,
        *,
        canvas: tuple[int, int],
        prompt: str,
    ) -> Image.Image:
        return self._placeholder(canvas, prompt, "candidate")

    def generate_key_pose(
        self,
        *,
        canvas: tuple[int, int],
        reference_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        return self._placeholder(canvas, prompt, "key")

    def generate_interframe(
        self,
        *,
        canvas: tuple[int, int],
        source_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        # For the mock, just return the source image unchanged — it's already
        # a PIL blend of adjacent key frames from the caller.
        w, h = canvas
        if source_img.size != (w, h):
            return source_img.resize((w, h), Image.LANCZOS).convert("RGBA")
        return source_img.convert("RGBA")

    def cost_estimate_usd(self, *, n_candidates: int, n_frames: int) -> float:
        return 0.00

    # ── internal ──

    def _placeholder(
        self, canvas: tuple[int, int], prompt: str, kind: str
    ) -> Image.Image:
        w, h = canvas
        rng = random.Random(hash((prompt, kind)) & 0xFFFFFFFF)

        bg_color = (
            rng.randint(80, 200),
            rng.randint(80, 200),
            rng.randint(80, 200),
            255,
        )
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Simple blob silhouette centred on canvas
        cx, cy = w // 2, h // 2
        bw, bh = w * 6 // 10, h * 7 // 10
        draw.ellipse(
            [cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2],
            fill=bg_color,
            outline=(0, 0, 0, 255),
            width=2,
        )
        return img

"""Mock pixel-art provider — offline, no API key, returns placeholder PNGs.

Useful for end-to-end testing of the pipeline structure (catalog parsing,
filesystem layout, review UI) without spending API credits or waiting for
network calls. Outputs are deterministic colored placeholder tiles labeled
with a short fragment of the prompt so you can see the pipeline routed each
asset to the right place.
"""

from __future__ import annotations

import hashlib
import io
import random

from PIL import Image, ImageDraw, ImageFont

from ..base import PixelArtProvider


class MockProvider(PixelArtProvider):
    @property
    def name(self) -> str:
        return "mock"

    def generate(
        self,
        prompt: str,
        size: tuple[int, int],
        n: int = 1,
        style_reference: bytes | None = None,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        return [_render_tile(prompt, size, palette, variant=i) for i in range(n)]

    def img2img(
        self,
        prompt: str,
        source_image: bytes,
        size: tuple[int, int],
        strength: float = 0.75,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        # Decode source as a tint hint, then render placeholders matching it.
        return [
            _render_tile(prompt, size, palette, variant=i, source=source_image)
            for i in range(n)
        ]

    def inpaint(
        self,
        prompt: str,
        source_image: bytes,
        mask_image: bytes,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        # Pretend to repaint the masked region by overlaying a slightly different tile.
        out = []
        src = Image.open(io.BytesIO(source_image)).convert("RGBA")
        mask = Image.open(io.BytesIO(mask_image)).convert("L")
        for i in range(n):
            patch_bytes = _render_tile(prompt + " (refined)", src.size, palette, variant=i)
            patch = Image.open(io.BytesIO(patch_bytes)).convert("RGBA")
            composed = Image.composite(patch, src, mask)
            buf = io.BytesIO()
            composed.save(buf, format="PNG")
            out.append(buf.getvalue())
        return out

    def cost_estimate(self, size: tuple[int, int], n: int) -> float:
        return 0.0


def _render_tile(
    prompt: str,
    size: tuple[int, int],
    palette: list[tuple[int, int, int]] | None,
    variant: int = 0,
    source: bytes | None = None,
) -> bytes:
    """Render a deterministic placeholder PNG for the given prompt+variant."""
    seed = int(hashlib.sha1(f"{prompt}|{variant}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    if palette:
        bg = palette[seed % len(palette)]
        fg = palette[(seed + 5) % len(palette)]
        accent = palette[(seed + 11) % len(palette)]
    else:
        bg = (rng.randint(20, 90), rng.randint(20, 60), rng.randint(20, 60))
        fg = (rng.randint(180, 255), rng.randint(120, 200), rng.randint(40, 100))
        accent = (rng.randint(200, 255), rng.randint(150, 220), rng.randint(40, 90))

    img = Image.new("RGBA", size, (*bg, 255))
    draw = ImageDraw.Draw(img)

    border = max(1, min(size) // 16)
    draw.rectangle(
        [border, border, size[0] - border - 1, size[1] - border - 1],
        outline=fg,
        width=max(1, border // 2),
    )

    cx, cy = size[0] // 2, size[1] // 2
    r = min(size) // 4
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)

    label = (prompt[:14] + "…") if len(prompt) > 14 else prompt
    try:
        font = ImageFont.load_default()
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        draw.text(((size[0] - tw) // 2, size[1] - th - border), label, fill=fg, font=font)
    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

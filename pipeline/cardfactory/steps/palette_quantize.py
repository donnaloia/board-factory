"""Snap illustration RGB to deck/board palette (cardfactory-local, no cross-imports)."""

from __future__ import annotations

from PIL import Image


def quantize_to_rgb_palette(
    img: Image.Image,
    palette_colors: list[tuple[int, int, int]],
) -> Image.Image:
    """Return ``img`` with RGB snapped to ``palette_colors``; alpha unchanged."""
    if not palette_colors:
        return img.convert("RGBA")

    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()

    pal_img = Image.new("P", (1, 1))
    n_colors = min(len(palette_colors), 256)
    flat: list[int] = []
    for sr, sg, sb in palette_colors[:n_colors]:
        flat.extend([sr, sg, sb])
    lr, lg, lb = palette_colors[n_colors - 1]
    while len(flat) < 768:
        flat.extend([lr, lg, lb])
    pal_img.putpalette(flat)

    rgb = Image.merge("RGB", (r, g, b))
    quantized = rgb.quantize(palette=pal_img, dither=0).convert("RGB")
    return Image.merge("RGBA", (*quantized.split(), a))

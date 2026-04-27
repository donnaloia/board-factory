"""Palette extraction, persistence, and quantization.

This module owns the project's shared palette discipline. The flow is:

1. `extract_palette(reference_image, n)` runs PIL's median-cut quantizer on the
   user's mockup to extract a representative N-color palette.
2. The palette is saved as both `.gpl` (for compatibility with Aseprite/GIMP)
   and `.json` (for fast loading by later pipeline steps).
3. Every cleanup pass reads the JSON palette and `quantize_to_palette()` snaps
   any new image to those exact colors.

Result: every approved asset shares the same N colors with no drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from PIL import Image


def extract_palette(image_path: Path, n: int = 24) -> list[tuple[int, int, int]]:
    """Extract the N most representative colors from `image_path` via median-cut."""
    img = Image.open(image_path).convert("RGB")
    quantized = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = quantized.getpalette()[: n * 3]
    return [tuple(palette[i : i + 3]) for i in range(0, n * 3, 3)]


def save_palette(palette: list[tuple[int, int, int]], json_path: Path, gpl_path: Path) -> None:
    """Save palette as both JSON (for code) and .gpl (for art tools)."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps([list(c) for c in palette]))

    gpl_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["GIMP Palette", f"Name: BoardFactory ({len(palette)} colors)", "Columns: 8", "#"]
    for r, g, b in palette:
        lines.append(f"{r:>3} {g:>3} {b:>3}\tRGB-{r:02x}{g:02x}{b:02x}")
    gpl_path.write_text("\n".join(lines) + "\n")


def load_palette(json_path: Path) -> list[tuple[int, int, int]]:
    return [tuple(c) for c in json.loads(json_path.read_text())]


def quantize_to_palette(
    img: Image.Image, palette: list[tuple[int, int, int]]
) -> Image.Image:
    """Snap every pixel of `img` to the nearest color in `palette`.

    Preserves alpha by quantizing only RGB channels and re-attaching alpha.
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    rgb = img.convert("RGB")
    alpha = img.getchannel("A")

    # PIL needs a palette image as the target for `quantize(palette=...)`.
    pal_img = Image.new("P", (1, 1))
    flat = []
    for c in palette:
        flat.extend(c)
    flat.extend([0] * (768 - len(flat)))
    pal_img.putpalette(flat)

    quantized = rgb.quantize(palette=pal_img, dither=Image.Dither.NONE).convert("RGB")
    out = Image.merge("RGBA", (*quantized.split(), alpha))
    return out


def render_palette_swatch(
    palette: list[tuple[int, int, int]], cell: int = 64, cols: int = 8
) -> Image.Image:
    """Render a palette as a swatch grid PNG for visual inspection."""
    rows = (len(palette) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell), (32, 32, 32))
    for i, c in enumerate(palette):
        x, y = (i % cols) * cell, (i // cols) * cell
        for px in range(x, x + cell):
            for py in range(y, y + cell):
                img.putpixel((px, py), c)
    return img


def stitch_grid(images: Iterable[Image.Image], cell: tuple[int, int], cols: int = 4) -> Image.Image:
    """Stitch N images into a grid for the style sheet."""
    images = list(images)
    rows = (len(images) + cols - 1) // cols
    out = Image.new("RGBA", (cols * cell[0], rows * cell[1]), (0, 0, 0, 0))
    for i, im in enumerate(images):
        x, y = (i % cols) * cell[0], (i // cols) * cell[1]
        out.paste(im.resize(cell), (x, y))
    return out

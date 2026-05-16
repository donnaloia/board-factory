"""Palette quantization — reduce a generated frame to the token palette.

Takes a PIL RGBA image and the ``token_palette`` dict (hex strings) from
``design_lock.json``.  Uses ``Image.quantize`` with a small swatch table to
snap colours to the palette while preserving alpha.

The alpha channel is restored to the original values after quantization so
the transparent background stays transparent.
"""

from __future__ import annotations

from PIL import Image


def quantize_to_token_palette(
    img: Image.Image,
    token_palette: dict[str, list[str]],
) -> Image.Image:
    """Return ``img`` colour-snapped to the token palette (alpha preserved).

    ``token_palette`` format::

        {
            "body_neutral":     ["#c8a87a", ...],
            "accent_primary":   ["#7ab8c8", ...],
            "highlight_neutral":["#f5f0e8", ...],
        }
    """
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()

    # Collect all palette swatches
    swatches = _all_swatches(token_palette)
    if not swatches:
        return rgba

    # Build a small palette image for PIL quantize
    n = len(swatches)
    pal_img = Image.new("P", (1, 1))
    flat: list[int] = []
    for sr, sg, sb in swatches:
        flat.extend([sr, sg, sb])
    flat.extend([0] * (768 - len(flat)))  # PIL palette must be 256 * 3 bytes
    pal_img.putpalette(flat)

    rgb = Image.merge("RGB", (r, g, b))
    quantized = rgb.quantize(palette=pal_img, dither=0).convert("RGB")

    out = Image.merge("RGBA", (*quantized.split(), a))
    return out


def _all_swatches(palette: dict[str, list[str]]) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for hexes in palette.values():
        for h in hexes:
            h = h.lstrip("#")
            if len(h) == 6:
                out.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    # Deduplicate while preserving order
    seen: set[tuple[int, int, int]] = set()
    deduped = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped[:256]  # PIL quantize palette capped at 256 colours

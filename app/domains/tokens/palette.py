"""OKLch-based token palette computation (§3.9.1).

Converts a board's raw color swatches into a three-slot ``TokenPalette``
that governs AI prompt language and palette-quantization during frame
generation:

* ``body_neutral``    — 4–6 low-chroma swatches that define the character body.
* ``accent_primary``  — 4–6 steps built around a split-complement accent hue.
* ``highlight_neutral`` — 2–3 near-white or pale-neutral highlights.

All color math is in OKLch (Björn Ottosson, 2020) which has perceptually
uniform hue and chroma axes.  HSL is not used because its hue uniformity
is poor (blue/yellow are visually heavier than the angle implies).
"""

from __future__ import annotations

import math
from typing import NamedTuple


# ── OKLab / OKLch conversions ────────────────────────────────────────────────

class _OKLch(NamedTuple):
    L: float   # lightness  0–1
    C: float   # chroma     0–0.4 typical
    H: float   # hue angle  0–360°


def _srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def srgb8_to_oklch(r: int, g: int, b: int) -> _OKLch:
    """Convert 8-bit sRGB to OKLch (Ottosson 2020)."""
    lr = _srgb_to_linear(r / 255.0)
    lg = _srgb_to_linear(g / 255.0)
    lb = _srgb_to_linear(b / 255.0)

    # Linear sRGB → LMS (M₁ matrix)
    l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
    m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
    s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb

    l_ = _cbrt(l)
    m_ = _cbrt(m)
    s_ = _cbrt(s)

    # LMS → OKLab (M₂ matrix)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_

    C = math.sqrt(a * a + b_ * b_)
    H = (math.degrees(math.atan2(b_, a)) + 360.0) % 360.0
    return _OKLch(L, C, H)


def oklch_to_srgb8(L: float, C: float, H: float) -> tuple[int, int, int]:
    """Convert OKLch back to clamped 8-bit sRGB."""
    rad = math.radians(H)
    a = C * math.cos(rad)
    b_ = C * math.sin(rad)

    # OKLab → LMS (M₂⁻¹ matrix)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b_
    m_ = L - 0.1055613458 * a - 0.0638541728 * b_
    s_ = L - 0.0894841775 * a - 1.2914855480 * b_

    l = l_ ** 3
    m = m_ ** 3
    s = s_ ** 3

    # LMS → Linear sRGB (M₁⁻¹ matrix)
    lr = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    lg = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    lb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    r = int(round(_linear_to_srgb(lr) * 255))
    g = int(round(_linear_to_srgb(lg) * 255))
    b = int(round(_linear_to_srgb(lb) * 255))
    return (
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


def _circular_mean_hue(hues: list[float]) -> float:
    """Circular mean of hue angles (degrees)."""
    if not hues:
        return 0.0
    sin_sum = sum(math.sin(math.radians(h)) for h in hues)
    cos_sum = sum(math.cos(math.radians(h)) for h in hues)
    return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360.0) % 360.0


def _circular_dist(h1: float, h2: float) -> float:
    """Shortest angular distance between two hue angles (0–180)."""
    d = abs(h1 - h2) % 360.0
    return 360.0 - d if d > 180.0 else d


def _hue_ramp(
    H_accent: float, C_accent: float, steps: int = 5
) -> list[tuple[int, int, int]]:
    """Build ``steps`` sRGB colours by varying L while holding H, C fixed.

    L sweeps from 0.55 (mid) to 0.75 (light) to give a paint-friendly ramp.
    """
    colours = []
    for i in range(steps):
        L = 0.55 + 0.20 * (i / max(steps - 1, 1))
        colours.append(oklch_to_srgb8(L, C_accent, H_accent))
    return colours


# ── §3.9.1 token palette algorithm ──────────────────────────────────────────

class TokenPalette(NamedTuple):
    body_neutral: list[tuple[int, int, int]]
    accent_primary: list[tuple[int, int, int]]
    highlight_neutral: list[tuple[int, int, int]]


def compute_token_palette(
    palette_colors: list[tuple[int, int, int]],
    *,
    chroma_high_fraction: float = 0.30,
    accent_target_C: float = 0.14,
) -> TokenPalette:
    """Compute a token palette from a board's raw color swatches.

    ``palette_colors`` — list of (R, G, B) 8-bit tuples.  Typically the
    output of the board's ``style_palette`` column (parsed from hex strings).

    Steps
    -----
    1. Convert all swatches to OKLch.
    2. Split into *high-chroma* (top ``chroma_high_fraction``) and *low-chroma*
       buckets.
    3. ``body_neutral`` = 4–6 low-chroma swatches, sorted light→dark.
    4. Compute ``H_mean`` = circular mean of low-chroma hue angles.
    5. ``H_forbidden`` = hue angles of high-chroma swatches.
    6. Candidate accent hues: split-complement (H_mean ± 165–195°) + triad
       (H_mean ± 120°).  Score by min distance to H_forbidden; pick winner.
    7. ``accent_primary`` = 5-step L-ramp at (H_accent, ``accent_target_C``).
    8. ``highlight_neutral`` = 2–3 near-white swatches (L ≥ 0.88, C ≤ 0.03).
    """
    if not palette_colors:
        return _fallback_palette()

    lch = [srgb8_to_oklch(r, g, b) for r, g, b in palette_colors]

    # 2. Split by chroma
    sorted_by_C = sorted(lch, key=lambda x: x.C, reverse=True)
    split = max(1, int(len(sorted_by_C) * chroma_high_fraction))
    high_chroma = sorted_by_C[:split]
    low_chroma = sorted_by_C[split:]

    # 3. body_neutral — keep up to 6 low-chroma, sort lightest→darkest
    body_lch = sorted(low_chroma, key=lambda x: x.L, reverse=True)[:6]
    if len(body_lch) < 2:
        body_lch = sorted_by_C[-6:]  # fallback: just take the darkest
    body_neutral = [oklch_to_srgb8(c.L, c.C, c.H) for c in body_lch]

    # 4. H_mean of low-chroma swatches
    H_mean = _circular_mean_hue([c.H for c in low_chroma]) if low_chroma else 0.0

    # 5. Forbidden hue angles (high-chroma)
    forbidden = [c.H for c in high_chroma]

    # 6. Score candidate accent hues
    candidates = [
        H_mean + 180.0,   # direct complement
        H_mean + 165.0,
        H_mean + 195.0,
        H_mean + 120.0,   # triad
        H_mean + 240.0,
    ]
    candidates = [h % 360.0 for h in candidates]

    def _score(h: float) -> float:
        if not forbidden:
            return 180.0
        return min(_circular_dist(h, f) for f in forbidden)

    H_accent = max(candidates, key=_score)

    # 7. accent_primary ramp
    accent_primary = _hue_ramp(H_accent, accent_target_C, steps=5)

    # 8. highlight_neutral — near-white, low chroma
    highlights_lch = [c for c in lch if c.L >= 0.88 and c.C <= 0.03]
    if len(highlights_lch) < 2:
        # synthesise: near-white nudged slightly toward H_mean
        highlights_lch = [
            _OKLch(0.95, 0.01, H_mean),
            _OKLch(0.90, 0.01, H_mean),
        ]
    highlight_neutral = [
        oklch_to_srgb8(c.L, c.C, c.H) for c in highlights_lch[:3]
    ]

    return TokenPalette(
        body_neutral=body_neutral,
        accent_primary=accent_primary,
        highlight_neutral=highlight_neutral,
    )


def palette_to_dict(tp: TokenPalette) -> dict:
    """Serialise TokenPalette to a JSON-safe dict (hex strings)."""
    def _to_hex(swatches: list[tuple[int, int, int]]) -> list[str]:
        return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in swatches]

    return {
        "body_neutral": _to_hex(tp.body_neutral),
        "accent_primary": _to_hex(tp.accent_primary),
        "highlight_neutral": _to_hex(tp.highlight_neutral),
    }


def palette_from_dict(d: dict) -> TokenPalette:
    """Deserialise a palette dict back to a TokenPalette (for use in prompts)."""
    def _from_hex(hexes: list[str]) -> list[tuple[int, int, int]]:
        out = []
        for h in hexes:
            h = h.lstrip("#")
            out.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        return out

    return TokenPalette(
        body_neutral=_from_hex(d.get("body_neutral", [])),
        accent_primary=_from_hex(d.get("accent_primary", [])),
        highlight_neutral=_from_hex(d.get("highlight_neutral", [])),
    )


def palette_sentence(d: dict) -> str:
    """Convert a palette dict to a short natural-language sentence for AI prompts.

    Example: "Body: warm cream, cocoa. Trim: steel-blue. Highlights: ivory."
    """
    def _hex_to_name(h: str) -> str:
        h = h.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        lch = srgb8_to_oklch(r, g, b)
        return _oklch_name(lch.L, lch.C, lch.H)

    body = ", ".join(_hex_to_name(h) for h in d.get("body_neutral", [])[:3])
    accent = ", ".join(_hex_to_name(h) for h in d.get("accent_primary", [])[:2])
    highlight = ", ".join(_hex_to_name(h) for h in d.get("highlight_neutral", [])[:2])

    parts = []
    if body:
        parts.append(f"Body: {body}")
    if accent:
        parts.append(f"Trim: {accent}")
    if highlight:
        parts.append(f"Highlights: {highlight}")
    return ". ".join(parts) + "." if parts else ""


def _oklch_name(L: float, C: float, H: float) -> str:
    """Very rough OKLch → descriptive English colour name (for prompt wording)."""
    if C < 0.03:
        if L > 0.90:
            return "ivory"
        if L > 0.70:
            return "pale grey"
        if L > 0.45:
            return "mid grey"
        return "charcoal"

    # Basic hue bucketing in 30° sectors
    hue_names = [
        (15,  "red"),
        (45,  "orange"),
        (75,  "yellow"),
        (105, "yellow-green"),
        (135, "green"),
        (165, "teal"),
        (195, "cyan"),
        (225, "sky-blue"),
        (255, "blue"),
        (285, "violet"),
        (315, "purple"),
        (345, "magenta"),
        (375, "red"),   # wrap
    ]
    hue = H % 360.0
    hue_label = "crimson"
    for threshold, label in hue_names:
        if hue < threshold:
            hue_label = label
            break

    if L > 0.75:
        return f"light {hue_label}"
    if L < 0.40:
        return f"dark {hue_label}"
    return hue_label


def _fallback_palette() -> TokenPalette:
    return TokenPalette(
        body_neutral=[
            (220, 195, 165),
            (185, 155, 115),
            (140, 110, 75),
            (90, 65, 40),
        ],
        accent_primary=[
            (100, 160, 200),
            (80, 140, 185),
            (60, 115, 165),
            (45, 90, 140),
            (30, 65, 110),
        ],
        highlight_neutral=[
            (245, 240, 232),
            (230, 224, 215),
        ],
    )

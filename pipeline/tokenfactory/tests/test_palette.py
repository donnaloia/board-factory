"""Tests for OKLch palette computation (§3.9.1).

Verifies the math converts correctly and the accent-hue selection avoids
the dominant palette hues.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Make the app's palette module reachable from the pipeline test tree
_APP = Path(__file__).resolve().parents[3] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from domains.tokens.palette import (
    TokenPalette,
    _circular_dist,
    compute_token_palette,
    oklch_to_srgb8,
    palette_from_dict,
    palette_sentence,
    palette_to_dict,
    srgb8_to_oklch,
)


# ── round-trip sRGB → OKLch → sRGB ───────────────────────────────────────────


def test_oklch_roundtrip_pure_red():
    r, g, b = 255, 0, 0
    L, C, H = srgb8_to_oklch(r, g, b)
    assert L > 0 and C > 0
    r2, g2, b2 = oklch_to_srgb8(L, C, H)
    assert abs(r2 - r) <= 2
    assert abs(g2 - g) <= 2
    assert abs(b2 - b) <= 2


def test_oklch_roundtrip_pure_white():
    L, C, H = srgb8_to_oklch(255, 255, 255)
    assert L > 0.99
    assert C < 0.01
    r2, g2, b2 = oklch_to_srgb8(L, C, H)
    assert r2 == 255 and g2 == 255 and b2 == 255


def test_oklch_roundtrip_pure_black():
    L, C, H = srgb8_to_oklch(0, 0, 0)
    assert L < 0.01
    r2, g2, b2 = oklch_to_srgb8(L, C, H)
    assert r2 == 0 and g2 == 0 and b2 == 0


def test_oklch_roundtrip_mid_grey():
    for v in (64, 128, 192):
        L, C, H = srgb8_to_oklch(v, v, v)
        assert C < 0.005, f"grey (v={v}) should have near-zero chroma"
        r2, g2, b2 = oklch_to_srgb8(L, C, H)
        assert abs(r2 - v) <= 2


# ── circular_dist ─────────────────────────────────────────────────────────────


def test_circular_dist_same():
    assert _circular_dist(90.0, 90.0) == 0.0


def test_circular_dist_opposite():
    assert abs(_circular_dist(0.0, 180.0) - 180.0) < 1e-9


def test_circular_dist_wraparound():
    assert abs(_circular_dist(350.0, 10.0) - 20.0) < 1e-9


# ── compute_token_palette ─────────────────────────────────────────────────────


def test_palette_from_single_swatch():
    tp = compute_token_palette([(200, 170, 120)])
    assert len(tp.body_neutral) >= 1
    assert len(tp.accent_primary) >= 1
    assert len(tp.highlight_neutral) >= 1


def test_palette_produces_distinct_accent():
    # Input: monochromatic warm browns (all low-chroma, same hue)
    warm_browns = [(180, 140, 90), (160, 120, 70), (140, 100, 55), (120, 80, 40)]
    tp = compute_token_palette(warm_browns)
    # Accent hue should differ from body hues by at least 90°
    body_hues = [srgb8_to_oklch(*c).H for c in warm_browns]
    for accent_rgb in tp.accent_primary:
        accent_hue = srgb8_to_oklch(*accent_rgb).H
        min_dist = min(_circular_dist(accent_hue, h) for h in body_hues)
        assert min_dist >= 60, (
            f"Accent hue {accent_hue:.1f}° too close to body hue (min dist {min_dist:.1f}°)"
        )


def test_palette_empty_input():
    tp = compute_token_palette([])
    assert len(tp.body_neutral) >= 1
    assert len(tp.accent_primary) >= 1


# ── serialisation ─────────────────────────────────────────────────────────────


def test_palette_dict_roundtrip():
    tp = compute_token_palette([(180, 140, 90), (100, 80, 50), (240, 235, 220)])
    d = palette_to_dict(tp)
    assert isinstance(d["body_neutral"], list)
    assert all(isinstance(h, str) and h.startswith("#") for h in d["body_neutral"])

    tp2 = palette_from_dict(d)
    assert len(tp2.body_neutral) == len(tp.body_neutral)
    assert len(tp2.accent_primary) == len(tp.accent_primary)


def test_palette_sentence_non_empty():
    tp = compute_token_palette([(180, 140, 90), (100, 80, 50)])
    d = palette_to_dict(tp)
    sentence = palette_sentence(d)
    assert len(sentence) > 0
    assert "Body:" in sentence or "Trim:" in sentence

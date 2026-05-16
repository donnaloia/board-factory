"""Tests for cardfactory mask rasterization."""

from __future__ import annotations

import pytest
from PIL import Image

from cardfactory.steps.masks import (
    build_m_art,
    build_m_stats,
    build_m_chrome_paint,
    clamp_forbidden_zones,
    mask_hash,
)

CANVAS = (720, 1008)
INNER = {"x": 72, "y": 101, "w": 576, "h": 806}

ILL_REGION = {"x": 0, "y": 0, "width": 1, "height": 0.6667}
STATS_REGION = {"x": 0, "y": 0.6667, "width": 1, "height": 0.3333}
TYPO_PAD = {"top": 0.12, "right": 0.08, "bottom": 0.1, "left": 0.08}


def test_m_art_size():
    m = build_m_art(CANVAS, INNER, ILL_REGION)
    assert m.size == CANVAS


def test_m_art_white_inside_hull():
    m = build_m_art(CANVAS, INNER, ILL_REGION)
    cx = INNER["x"] + INNER["w"] // 2
    cy = INNER["y"] + INNER["h"] // 4  # top quarter of inner hull = illustration
    r, g, b, a = m.getpixel((cx, cy))
    assert r == 255 and a == 255, "Center of illustration region should be white"


def test_m_stats_and_m_art_are_disjoint():
    m_art = build_m_art(CANVAS, INNER, ILL_REGION)
    m_stats = build_m_stats(CANVAS, INNER, STATS_REGION)

    art_px = m_art.convert("L")
    stats_px = m_stats.convert("L")

    # No pixel should be white in both masks simultaneously
    from PIL import ImageChops
    overlap = ImageChops.multiply(art_px, stats_px)
    max_val = max(overlap.getdata())
    assert max_val == 0, "Art and stats masks must be disjoint"


def test_m_chrome_paint_excludes_illustration():
    m = build_m_chrome_paint(CANVAS, INNER, ILL_REGION, STATS_REGION, TYPO_PAD)
    # Center of illustration aperture must be black (forbidden)
    cx = INNER["x"] + INNER["w"] // 2
    cy = INNER["y"] + INNER["h"] // 4
    r, g, b, a = m.getpixel((cx, cy))
    assert r == 0, "Illustration aperture must be forbidden in M_chrome_paint"


def test_m_chrome_paint_allows_frame_ring():
    m = build_m_chrome_paint(CANVAS, INNER, ILL_REGION, STATS_REGION, TYPO_PAD)
    # Top-left corner is in the frame ring — must be white
    r, g, b, a = m.getpixel((10, 10))
    assert r == 255, "Frame ring (outside inner hull) must be allowed in M_chrome_paint"


def test_mask_hash_is_deterministic():
    m1 = build_m_art(CANVAS, INNER, ILL_REGION)
    m2 = build_m_art(CANVAS, INNER, ILL_REGION)
    assert mask_hash(m1) == mask_hash(m2)


def test_clamp_forbidden_zones():
    img = Image.new("RGBA", CANVAS, (200, 100, 50, 255))
    ill_rect = (100, 100, 400, 600)
    stats_rect = (100, 700, 400, 900)
    clamped = clamp_forbidden_zones(img, ill_rect, stats_rect)
    # Inside illustration rect must be transparent
    _, _, _, a = clamped.getpixel((250, 350))
    assert a == 0
    # Outside forbidden zones must remain opaque
    _, _, _, a = clamped.getpixel((10, 10))
    assert a == 255

"""Tests for mask refine + palette quantize helpers."""

from __future__ import annotations

from PIL import Image

from cardfactory.steps.mask_refine import (
    build_interior_window_edit_mask,
    refine_m_art_with_frame_hole,
)
from cardfactory.steps.palette_quantize import quantize_to_rgb_palette
from cardfactory.steps.prompt_extra import format_palette_clause


def test_format_palette_clause_empty():
    assert format_palette_clause([]) == ""


def test_format_palette_clause_hexes():
    s = format_palette_clause([(255, 0, 0), (0, 128, 64)])
    assert "#ff0000" in s
    assert "#008040" in s


def test_build_interior_window_is_continuous_hull():
    w, h = 40, 40
    inner = {"x": 8, "y": 8, "w": 24, "h": 24}
    frame = Image.new("RGBA", (w, h), (200, 100, 50, 255))
    px = frame.load()
    ix, iy, iw, ih = inner["x"], inner["y"], inner["w"], inner["h"]
    for yy in range(iy, iy + ih):
        for xx in range(ix, ix + iw):
            px[xx, yy] = (0, 0, 0, 0)
    m = build_interior_window_edit_mask(
        (w, h), inner, frame, hole_alpha_threshold=48
    )
    ml = m.convert("L")
    mid_y = iy + ih // 2
    # Band seam: full width of hull is editable (no zero-row gap between art/stats).
    for xx in range(ix + 1, ix + iw - 1):
        assert ml.getpixel((xx, mid_y)) == 255
    assert ml.getpixel((5, 5)) == 0  # outside hull


def test_refine_m_art_respects_opaque_frame():
    w, h = 40, 40
    m_art = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    frame = Image.new("RGBA", (w, h), (200, 100, 50, 255))
    # punch transparent 10x10 hole top-left
    px = frame.load()
    for y in range(12):
        for x in range(12):
            px[x, y] = (0, 0, 0, 0)
    refined = refine_m_art_with_frame_hole(m_art, frame, hole_alpha_threshold=48)
    rl = refined.convert("L")
    assert rl.getpixel((20, 20)) == 0  # under opaque frame
    assert rl.getpixel((5, 5)) == 255  # in hole


def test_quantize_snaps_to_palette():
    img = Image.new("RGBA", (10, 10), (200, 20, 20, 255))
    out = quantize_to_rgb_palette(img, [(0, 0, 255)])
    r, g, b, a = out.getpixel((0, 0))
    assert (r, g, b) == (0, 0, 255)
    assert a == 255

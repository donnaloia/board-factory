"""Tests for layer compositing."""

from __future__ import annotations

from PIL import Image, ImageDraw

from PIL import ImageChops

from cardfactory.steps.composite import (
    apply_art_mat_fill,
    apply_committed_frame_authority,
    blend_single_pass_under_frame_holes,
    build_single_pass_art_layer,
    layer_composite,
    seal_single_pass_with_frame_on_top,
    flat_stats_background,
)
from cardfactory.steps.mask_refine import inset_mask_px
from cardfactory.steps.masks import build_m_art, build_m_stats

CANVAS = (720, 1008)
INNER = {"x": 72, "y": 101, "w": 576, "h": 806}
ILL_REGION = {"x": 0, "y": 0, "width": 1, "height": 0.6667}
STATS_REGION = {"x": 0, "y": 0.6667, "width": 1, "height": 0.3333}


def _solid(color):
    return Image.new("RGBA", CANVAS, color)


def test_composite_output_size():
    m_art = build_m_art(CANVAS, INNER, ILL_REGION)
    m_stats = build_m_stats(CANVAS, INNER, STATS_REGION)
    result = layer_composite(
        canvas=CANVAS,
        illustration=_solid((100, 150, 200, 255)),
        m_art=m_art,
        stats_background=flat_stats_background(CANVAS),
        m_stats=m_stats,
        frame_png=_solid((40, 30, 20, 0)),  # transparent frame
    )
    assert result.size == CANVAS


def test_frame_wins_at_edges():
    """Frame (last layer) should overwrite corners if opaque."""
    frame_color = (255, 0, 0, 255)
    frame = _solid(frame_color)
    m_art = build_m_art(CANVAS, INNER, ILL_REGION)
    m_stats = build_m_stats(CANVAS, INNER, STATS_REGION)
    result = layer_composite(
        canvas=CANVAS,
        illustration=_solid((0, 255, 0, 255)),
        m_art=m_art,
        stats_background=flat_stats_background(CANVAS),
        m_stats=m_stats,
        frame_png=frame,
    )
    # Top-left corner — frame is on top so it should be red
    r, g, b, a = result.getpixel((5, 5))
    assert r == 255 and g == 0 and b == 0, "Frame must win at corners"


def test_flat_stats_background_size():
    bg = flat_stats_background(CANVAS)
    assert bg.size == CANVAS
    assert bg.mode == "RGBA"


def test_single_pass_pin_keeps_frame_outside_edit_mask():
    canvas = (32, 32)
    painted = Image.new("RGBA", canvas, (0, 0, 255, 255))
    frame = Image.new("RGBA", canvas, (255, 0, 0, 255))
    m = Image.new("L", canvas, 0)
    d = ImageDraw.Draw(m)
    d.rectangle((8, 8, 23, 23), fill=255)
    m_integrated = Image.merge("RGBA", (m, m, m, m))
    pinned = blend_single_pass_under_frame_holes(painted, frame, m_integrated)
    assert pinned.getpixel((2, 2))[:3] == (255, 0, 0)
    assert pinned.getpixel((16, 16))[:3] == (0, 0, 255)


def test_single_pass_art_layer_frame_is_true_overlay():
    """Interior art on transparent canvas; opaque frame with hole composites on top."""
    canvas = (32, 32)
    painted = Image.new("RGBA", canvas, (0, 0, 255, 255))
    frame = Image.new("RGBA", canvas, (255, 0, 0, 255))
    fr = frame.load()
    for y in range(8, 24):
        for x in range(8, 24):
            fr[x, y] = (0, 0, 0, 0)
    m = Image.new("L", canvas, 0)
    d = ImageDraw.Draw(m)
    d.rectangle((8, 8, 23, 23), fill=255)
    m_rgba = Image.merge("RGBA", (m, m, m, m))
    art_layer = build_single_pass_art_layer(canvas, painted, m_rgba)
    out = Image.alpha_composite(art_layer, frame)
    assert out.getpixel((4, 4))[:3] == (255, 0, 0)
    assert out.getpixel((16, 16))[:3] == (0, 0, 255)


def test_seal_puts_frame_on_top_of_typography():
    canvas = (32, 32)
    interior = Image.new("RGBA", canvas, (0, 0, 0, 0))
    frame = Image.new("RGBA", canvas, (200, 200, 200, 255))
    typo = Image.new("RGBA", canvas, (0, 0, 0, 0))
    out = seal_single_pass_with_frame_on_top(interior, frame, typo)
    assert out.getpixel((5, 5)) == (200, 200, 200, 255)


def test_frame_authority_restores_chrome_over_interior_bleed():
    canvas = (16, 16)
    frame = Image.new("RGBA", canvas, (0, 0, 0, 0))
    for y in range(16):
        frame.putpixel((0, y), (255, 0, 0, 255))
    card = Image.new("RGBA", canvas, (0, 255, 0, 255))
    out = apply_committed_frame_authority(card, frame, chrome_alpha_threshold=48)
    assert out.getpixel((0, 8))[:3] == (255, 0, 0)
    assert out.getpixel((8, 8))[:3] == (0, 255, 0)


def test_frame_authority_stamps_semi_transparent_rim_over_model():
    """Semi-transparent rim: when stamped the result must be fully opaque (not a transparent gap)."""
    canvas = (8, 8)
    frame = Image.new("RGBA", canvas, (0, 0, 0, 0))
    for y in range(8):
        frame.putpixel((1, y), (255, 0, 0, 40))  # soft red rim, alpha=40
    card = Image.new("RGBA", canvas, (0, 200, 0, 255))

    # threshold=48: alpha=40 is below threshold → rim not stamped → card shows through
    no_stamp = apply_committed_frame_authority(card, frame, chrome_alpha_threshold=48)
    assert no_stamp.getpixel((1, 4))[:3] == (0, 200, 0)

    # threshold=0: alpha=40 > 0 → rim composited over card → fully opaque output with red tint
    stamped = apply_committed_frame_authority(card, frame, chrome_alpha_threshold=0)
    r, g, b, a = stamped.getpixel((1, 4))
    assert a == 255, "rim composite must produce a fully opaque pixel, not a semi-transparent gap"
    assert r > 30, "red rim should tint the result"
    assert g < 200, "card green reduced by frame blend"


def test_art_mat_fill_covers_ring():
    """Mat fill paints frame-sampled colour in the ring between full mask and inset mask."""
    canvas = (32, 32)
    # m_integrated: white square 8..24, black elsewhere
    m_outer = Image.new("RGBA", canvas, (0, 0, 0, 255))
    m_outer.paste(Image.new("RGBA", (16, 16), (255, 255, 255, 255)), (8, 8))
    # inset by 3px → white square 11..21
    m_inset = inset_mask_px(m_outer, px=3)

    card = Image.new("RGBA", canvas, (100, 150, 200, 255))  # blue-ish art
    frame = Image.new("RGBA", canvas, (200, 100, 50, 255))  # brown frame
    mat_color = (200, 100, 50)  # same as frame for this test

    result = apply_art_mat_fill(card, frame, m_outer, m_inset, mat_color)
    rl = result.convert("L")

    # Centre of inner region should be unchanged (art, not mat)
    assert result.getpixel((16, 16))[:3] == (100, 150, 200)
    # Outside the outer mask should be unchanged (not ring)
    assert result.getpixel((2, 2))[:3] == (100, 150, 200)
    # Ring pixel (inside outer, outside inset) should be mat colour
    ring_x, ring_y = 9, 9  # just inside outer (8..24), just outside inset (11..21)
    assert result.getpixel((ring_x, ring_y))[:3] == mat_color

"""Organic interior hole extraction from frame alpha."""

from __future__ import annotations

from PIL import Image, ImageDraw

from cardfactory.steps.interior_hole import build_organic_hole_masks


def test_organic_hole_follows_ellipse_not_rect() -> None:
    w, h = 80, 80
    inner = {"x": 10, "y": 10, "w": 60, "h": 60}
    frame = Image.new("RGBA", (w, h), (90, 60, 40, 255))
    draw = ImageDraw.Draw(frame)
    draw.ellipse((18, 18, 61, 61), fill=(0, 0, 0, 0))

    outer, paint, used_fb = build_organic_hole_masks(
        frame,
        (w, h),
        inner,
        hole_alpha_threshold=48,
        rim_erode_px=2,
        cc_bbox_pad_px=24,
        min_area_px=200,
    )
    assert used_fb is False
    ol = outer.convert("L")
    assert ol.getpixel((15, 15)) < 128
    assert ol.getpixel((40, 40)) > 200
    pl = paint.convert("L")
    assert pl.getpixel((40, 40)) > 200
    assert ol.getpixel((40, 40)) >= pl.getpixel((40, 40))


def test_organic_hole_rectangular_synthetic_frame() -> None:
    """Hole aligned with cardfactory synthetic committed-frame pattern."""
    w, h = 64, 64
    inner = {"x": 10, "y": 10, "w": 44, "h": 44}
    img = Image.new("RGBA", (w, h), (55, 45, 35, 255))
    hole = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
    img.paste(hole, (10, 10))
    outer, paint, used_fb = build_organic_hole_masks(
        img,
        (w, h),
        inner,
        hole_alpha_threshold=18,
        rim_erode_px=2,
        cc_bbox_pad_px=16,
        min_area_px=100,
    )
    assert used_fb is False
    assert outer.convert("L").getpixel((32, 32)) > 200
    assert paint.convert("L").getpixel((32, 32)) > 200


def test_organic_hole_fallback_when_no_transparent_pixels() -> None:
    """Fully opaque frame: organic seed fails; rectangular-hull path is used."""
    w, h = 64, 64
    inner = {"x": 10, "y": 10, "w": 44, "h": 44}
    frame = Image.new("RGBA", (w, h), (40, 40, 40, 255))
    outer, _paint, used_fb = build_organic_hole_masks(
        frame,
        (w, h),
        inner,
        hole_alpha_threshold=48,
        rim_erode_px=2,
        cc_bbox_pad_px=16,
        min_area_px=100,
    )
    assert used_fb is True
    # Hull ∩ empty alpha hole → no interior window pixels
    assert outer.convert("L").getpixel((32, 32)) < 128

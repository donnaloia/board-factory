"""Tests for tokenfactory.steps.canvas."""

from __future__ import annotations

from PIL import Image

from tokenfactory.steps.canvas import (
    alpha_bbox_height,
    normalize_character_scale_to_reference,
    register_to_canvas,
)


def _sprite(w: int, h: int, fill=(255, 0, 0, 255)) -> Image.Image:
    """Opaque rectangle touching edges → bbox equals canvas."""
    return Image.new("RGBA", (w, h), fill)


def test_alpha_bbox_height_empty():
    img = Image.new("RGBA", (16, 20), (0, 0, 0, 0))
    assert alpha_bbox_height(img) == 0


def test_alpha_bbox_height_full():
    img = _sprite(16, 24)
    assert alpha_bbox_height(img) == 24


def test_normalize_scales_to_reference_height():
    src = _sprite(16, 40)
    ref_h = 20
    out = normalize_character_scale_to_reference(src, ref_h)
    # NEAREST + rounding makes bbox height land within ±2 px of the target.
    assert abs(alpha_bbox_height(out) - ref_h) <= 2
    assert abs(out.height - ref_h) <= 2


def test_normalize_no_op_when_ref_tiny():
    src = _sprite(16, 40)
    out = normalize_character_scale_to_reference(src, 2)
    assert out.size == src.size


def test_registered_sprite_keeps_canvas_dims():
    """Pinned outputs stay ``canvas_w × canvas_h`` (caller invariant)."""
    blob = Image.new("RGBA", (64, 80), (0, 0, 0, 0))
    blob.paste(_sprite(32, 40), (16, 20))
    out = register_to_canvas(blob, 96, 128)
    assert out.size == (96, 128)

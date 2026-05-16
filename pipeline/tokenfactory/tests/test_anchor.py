"""Tests for tokenfactory.steps.anchor."""

from __future__ import annotations

from PIL import Image

from tokenfactory.steps.anchor import anchor_character_in_canvas, _DEFAULT_PIVOT_X, _DEFAULT_PIVOT_Y


def _canvas_with_sprite(
    canvas_w: int,
    canvas_h: int,
    sprite_w: int,
    sprite_h: int,
    offset_x: int,
    offset_y: int,
) -> Image.Image:
    """Transparent canvas with a solid opaque rectangle placed at an offset."""
    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    sprite = Image.new("RGBA", (sprite_w, sprite_h), (200, 100, 50, 255))
    out.paste(sprite, (offset_x, offset_y))
    return out


def test_output_is_canvas_size():
    img = _canvas_with_sprite(96, 128, 40, 80, 28, 24)
    out = anchor_character_in_canvas(img, 96, 128)
    assert out.size == (96, 128)


def test_output_is_rgba():
    img = _canvas_with_sprite(96, 128, 40, 80, 28, 24)
    out = anchor_character_in_canvas(img, 96, 128)
    assert out.mode == "RGBA"


def test_empty_frame_returned_unchanged():
    empty = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
    out = anchor_character_in_canvas(empty, 96, 128)
    assert out.size == (96, 128)
    assert out.split()[3].getbbox() is None


def test_bottom_centre_is_pinned_to_pivot():
    """After anchoring, the sprite's bottom-centre matches the target pivot."""
    canvas_w, canvas_h = 96, 128
    sprite_w, sprite_h = 40, 80

    # Place sprite at an arbitrary off-centre position
    img = _canvas_with_sprite(canvas_w, canvas_h, sprite_w, sprite_h, 10, 5)
    out = anchor_character_in_canvas(out := anchor_character_in_canvas(img, canvas_w, canvas_h),
                                     canvas_w, canvas_h)

    bb = out.split()[3].getbbox()
    assert bb is not None
    left, top, right, bottom = bb

    expected_cx = int(round(canvas_w * _DEFAULT_PIVOT_X))
    expected_bottom = int(round(canvas_h * _DEFAULT_PIVOT_Y))

    actual_cx = (left + right) // 2
    assert abs(actual_cx - expected_cx) <= 1, f"cx={actual_cx} expected≈{expected_cx}"
    assert abs(bottom - expected_bottom) <= 1, f"bottom={bottom} expected≈{expected_bottom}"


def test_different_offsets_produce_same_anchored_position():
    """Two frames of identical sprite but different starting positions should
    land at the same canvas position after anchoring."""
    canvas_w, canvas_h = 96, 128
    sprite_w, sprite_h = 30, 60

    frame_a = _canvas_with_sprite(canvas_w, canvas_h, sprite_w, sprite_h, 10, 20)
    frame_b = _canvas_with_sprite(canvas_w, canvas_h, sprite_w, sprite_h, 50, 40)

    out_a = anchor_character_in_canvas(frame_a, canvas_w, canvas_h)
    out_b = anchor_character_in_canvas(frame_b, canvas_w, canvas_h)

    bb_a = out_a.split()[3].getbbox()
    bb_b = out_b.split()[3].getbbox()
    assert bb_a is not None and bb_b is not None

    # Bottom edges must be at the same Y
    assert bb_a[3] == bb_b[3], f"bottom mismatch: {bb_a[3]} vs {bb_b[3]}"
    # Horizontal centres must be at the same X (±1 rounding)
    cx_a = (bb_a[0] + bb_a[2]) // 2
    cx_b = (bb_b[0] + bb_b[2]) // 2
    assert abs(cx_a - cx_b) <= 1, f"cx mismatch: {cx_a} vs {cx_b}"

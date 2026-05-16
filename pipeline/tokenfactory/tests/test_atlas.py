"""Tests for tokenfactory.steps.atlas packing."""

from __future__ import annotations

from PIL import Image

from tokenfactory.steps.atlas import pack_atlas


def _blank_frame(w: int = 16, h: int = 20) -> Image.Image:
    return Image.new("RGBA", (w, h), (128, 100, 80, 255))


def test_pack_single_clip():
    frames = [_blank_frame() for _ in range(4)]
    atlas, entries = pack_atlas({"idle": frames}, canvas_w=16, canvas_h=20, frame_fps=10)
    assert atlas.size == (4 * 16, 20)
    assert "idle" in entries
    assert len(entries["idle"].frames) == 4


def test_pack_two_clips():
    walk = [_blank_frame() for _ in range(6)]
    idle = [_blank_frame() for _ in range(4)]
    atlas, entries = pack_atlas(
        {"walk": walk, "idle": idle},
        canvas_w=16,
        canvas_h=20,
    )
    # Width = max(6, 4) * 16 = 96; Height = 2 * 20 = 40
    assert atlas.size == (6 * 16, 2 * 20)
    assert entries["walk"].frames[0].x == 0 and entries["walk"].frames[0].y == 0
    assert entries["idle"].frames[0].y == 20


def test_pack_flip_x_flag():
    frames = [_blank_frame() for _ in range(4)]
    _, entries = pack_atlas(
        {"walk_horizontal": frames},
        canvas_w=16,
        canvas_h=20,
        flip_x_clips={"walk_horizontal"},
    )
    assert entries["walk_horizontal"].flip_x is True


def test_pack_no_flip_x_by_default():
    frames = [_blank_frame() for _ in range(4)]
    _, entries = pack_atlas({"idle_breath": frames}, canvas_w=16, canvas_h=20)
    assert entries["idle_breath"].flip_x is False


def test_pack_empty_input():
    atlas, entries = pack_atlas({}, canvas_w=16, canvas_h=20)
    assert atlas.size == (16, 20)
    assert entries == {}

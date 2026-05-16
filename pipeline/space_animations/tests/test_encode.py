"""Encoder + loop-closure unit tests."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from space_animations.steps.encode import encode_clip, file_extension_for
from space_animations.steps.loop_close import close_loop


def _frames(n: int = 8, size=(16, 16)) -> list[Image.Image]:
    return [Image.new("RGBA", size, (i * 30 % 256, 80, 40, 255)) for i in range(n)]


def test_extension_aliases():
    assert file_extension_for("gif") == "gif"
    assert file_extension_for("apng") == "apng"
    assert file_extension_for("anything") == "gif"


def test_encode_gif_round_trip():
    raw = encode_clip(_frames(8), fps=10, encoding="gif")
    assert raw.startswith(b"GIF8")
    img = Image.open(io.BytesIO(raw))
    assert getattr(img, "is_animated", False)
    assert img.n_frames == 8


def test_encode_apng_round_trip():
    raw = encode_clip(_frames(6), fps=12, encoding="apng")
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    img = Image.open(io.BytesIO(raw))
    assert getattr(img, "is_animated", False)
    assert img.n_frames == 6


def test_encode_rejects_zero_fps():
    with pytest.raises(ValueError, match="fps"):
        encode_clip(_frames(2), fps=0, encoding="gif")


def test_encode_rejects_unknown_encoding():
    with pytest.raises(ValueError, match="encoding"):
        encode_clip(_frames(2), fps=10, encoding="webm")


def test_encode_rejects_empty():
    with pytest.raises(ValueError, match="at least one frame"):
        encode_clip([], fps=10, encoding="gif")


def test_close_loop_seamless_is_identity():
    fr = _frames(8)
    out = close_loop(fr, "seamless")
    assert len(out) == 8
    assert out[0] is fr[0]


def test_close_loop_pingpong_doubles_minus_endpoints():
    fr = _frames(8)
    out = close_loop(fr, "pingpong")
    assert len(out) == 8 + (8 - 2)


def test_close_loop_crossfade_preserves_count():
    fr = _frames(12)
    out = close_loop(fr, "crossfade")
    assert len(out) == 12


def test_close_loop_unknown_strategy_raises():
    with pytest.raises(ValueError):
        close_loop(_frames(4), "bounce")

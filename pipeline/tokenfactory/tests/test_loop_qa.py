"""Tests for tokenfactory.steps.loop_qa."""

from __future__ import annotations

import pytest
from PIL import Image

from tokenfactory.steps.loop_qa import LoopQAFailed, check_loop


def _frame(color: tuple[int, int, int, int], w: int = 16, h: int = 20) -> Image.Image:
    return Image.new("RGBA", (w, h), color)


def test_identical_frames_pass():
    frames = [_frame((100, 120, 80, 255))] * 4
    delta = check_loop(frames, threshold=0.07)
    assert delta < 1e-6


def test_similar_frames_pass():
    frames = [
        _frame((100, 120, 80, 255)),
        _frame((110, 115, 85, 255)),
        _frame((105, 118, 82, 255)),
        _frame((101, 121, 81, 255)),  # very close to first
    ]
    delta = check_loop(frames, threshold=0.07)
    assert delta < 0.07


def test_very_different_frames_fail():
    frames = [
        _frame((0, 0, 0, 255)),
        _frame((128, 128, 128, 255)),
        _frame((255, 255, 255, 255)),
    ]
    with pytest.raises(LoopQAFailed) as exc_info:
        check_loop(frames, threshold=0.07)
    assert exc_info.value.delta > 0.07


def test_single_frame_returns_zero():
    frames = [_frame((100, 100, 100, 255))]
    delta = check_loop(frames, threshold=0.07)
    assert delta == 0.0


def test_custom_threshold():
    frames = [_frame((100, 100, 100, 255)), _frame((110, 110, 110, 255))]
    with pytest.raises(LoopQAFailed):
        check_loop(frames, threshold=0.001)

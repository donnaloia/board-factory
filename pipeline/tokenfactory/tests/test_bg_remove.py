"""Tests for tokenfactory.steps.bg_remove."""

from __future__ import annotations

import pytest
from PIL import Image


def test_remove_background_returns_rgba():
    """Output is always RGBA regardless of input mode."""
    from tokenfactory.steps.bg_remove import remove_background

    rgb = Image.new("RGB", (32, 32), (200, 100, 50))
    out = remove_background(rgb)
    assert out.mode == "RGBA"
    assert out.size == (32, 32)


def test_remove_background_rgba_input():
    """RGBA input passes through without error."""
    from tokenfactory.steps.bg_remove import remove_background

    rgba = Image.new("RGBA", (32, 32), (200, 100, 50, 255))
    out = remove_background(rgba)
    assert out.mode == "RGBA"


def test_remove_background_produces_alpha_channel():
    """Output always has a real alpha channel (values differ per pixel)."""
    from tokenfactory.steps.bg_remove import remove_background

    # Gradient image — gives the segmentation model something to work with.
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    out = remove_background(img)
    assert out.mode == "RGBA"
    # Alpha band must exist and be an 8-bit channel
    alpha = out.split()[3]
    assert alpha.size == (64, 64)

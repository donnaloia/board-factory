"""Canonical Card Factory canvas geometry (width × height, portrait).

Layout templates under ``docs/card-factory/`` use *interior_normalized* rects; they do
not encode aspect ratio. The outer canvas aspect lives here and in
``docs/card-factory/layout-schematic.svg`` — keep them in sync when changing ratio.
"""

from __future__ import annotations

# Portrait width : height (playing-card–style; less tall than 9:16 phone frames).
CARD_ASPECT_WIDTH = 5
CARD_ASPECT_HEIGHT = 7

# Nominal pixels (720×1008); pipeline / previews should scale from this tuple.
CARD_DEFAULT_WIDTH = 720
CARD_DEFAULT_HEIGHT = 1008


def card_aspect_ratio() -> float:
    """Width divided by height (portrait, so value is below 1)."""
    return CARD_ASPECT_WIDTH / CARD_ASPECT_HEIGHT


def default_canvas_size() -> tuple[int, int]:
    return (CARD_DEFAULT_WIDTH, CARD_DEFAULT_HEIGHT)


def is_canvas_aspect(
    width: int,
    height: int,
    *,
    rel_tol: float = 0.02,
) -> bool:
    """True if ``width/height`` matches the canonical card aspect within ``rel_tol``."""
    if height <= 0:
        return False
    target = card_aspect_ratio()
    got = width / height
    return abs(got - target) <= rel_tol * max(target, got, 1e-9)

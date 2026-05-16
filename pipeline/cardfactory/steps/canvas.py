"""Canvas geometry helpers — aspect validation and scaling."""

from __future__ import annotations

from PIL import Image


CARD_ASPECT_W = 5
CARD_ASPECT_H = 7


def is_card_aspect(w: int, h: int, *, rel_tol: float = 0.02) -> bool:
    """True if w/h matches the 5:7 card aspect within ``rel_tol``."""
    if h <= 0:
        return False
    target = CARD_ASPECT_W / CARD_ASPECT_H
    got = w / h
    return abs(got - target) <= rel_tol * max(target, got, 1e-9)


def assert_card_aspect(w: int, h: int) -> None:
    """Raise ``ValueError`` if dimensions are not close to 5:7."""
    if not is_card_aspect(w, h):
        raise ValueError(
            f"Canvas {w}×{h} is not a 5:7 aspect ratio "
            f"(got {w/h:.4f}, expected {CARD_ASPECT_W/CARD_ASPECT_H:.4f})"
        )


def canonicalize_to_canvas(
    img: Image.Image, canvas: tuple[int, int]
) -> Image.Image:
    """Resize ``img`` to ``canvas`` (W, H) using high-quality Lanczos.

    Converts to RGBA first so all downstream compositing works uniformly.
    """
    target_w, target_h = canvas
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img.convert("RGBA")


def fit_to_canvas_nearest(img: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    """Resize to ``canvas`` with nearest-neighbor (preserves chunky pixels)."""
    target_w, target_h = canvas
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.NEAREST)
    return img.convert("RGBA")


def compute_inner_rect(
    canvas_w: int,
    canvas_h: int,
    *,
    margin: float = 0.10,
) -> dict[str, int]:
    """Compute the interior hull as a centered inset rectangle.

    ``margin`` is the fractional inset on each side (default 10%).
    Returns ``{x, y, w, h}`` in pixels.
    """
    x = round(canvas_w * margin)
    y = round(canvas_h * margin)
    w = canvas_w - 2 * x
    h = canvas_h - 2 * y
    return {"x": x, "y": y, "w": w, "h": h}

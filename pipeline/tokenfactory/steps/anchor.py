"""Canvas anchor — pin character bottom-center to a fixed pivot point.

After ``register_to_canvas`` places the character by geometric center,
inter-frame position still drifts because the *opaque* bbox shifts when the
model draws arms, hair, or accessories differently each frame.  This step
translates the already-canvas-sized sprite so the bottom of its alpha
bounding box (feet / hover base) always lands at a fixed pivot, eliminating
that drift deterministically regardless of model behaviour.

Pivot defaults
--------------
``pivot_x_frac = 0.5``   → horizontal centre of the canvas (symmetric)
``pivot_y_frac = 15/16`` → 15/16 down the canvas, matching the game layer's
                           ``pivot_y = int(canvas_h * 0.9375)``

If the sprite has no opaque pixels (e.g. empty frame) the image is returned
unchanged.  If the required shift would push content partially out of the
canvas boundary it is clipped naturally — the canvas stays at its fixed size.
"""

from __future__ import annotations

from PIL import Image

_DEFAULT_PIVOT_X = 0.5
_DEFAULT_PIVOT_Y = 15 / 16  # matches app/domains/tokens/services.py pivot_y


def anchor_character_in_canvas(
    frame: Image.Image,
    canvas_w: int,
    canvas_h: int,
    *,
    pivot_x_frac: float = _DEFAULT_PIVOT_X,
    pivot_y_frac: float = _DEFAULT_PIVOT_Y,
) -> Image.Image:
    """Translate ``frame`` so the character's bottom-centre lands at the pivot.

    Parameters
    ----------
    frame:
        A ``canvas_w × canvas_h`` RGBA image produced by ``register_to_canvas``.
    canvas_w, canvas_h:
        Token canvas dimensions — the output size is always identical.
    pivot_x_frac:
        Fraction of ``canvas_w`` for the target horizontal centre.
    pivot_y_frac:
        Fraction of ``canvas_h`` for the target bottom edge (feet / base).
    """
    rgba = frame.convert("RGBA")
    bb = rgba.split()[3].getbbox()
    if bb is None:
        return rgba

    left, top, right, bottom = bb
    frame_cx = (left + right) // 2
    frame_bottom = bottom

    target_cx = int(round(canvas_w * pivot_x_frac))
    target_bottom = int(round(canvas_h * pivot_y_frac))

    dx = target_cx - frame_cx
    dy = target_bottom - frame_bottom

    if dx == 0 and dy == 0:
        return rgba

    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    out.paste(rgba, (dx, dy), rgba)
    return out

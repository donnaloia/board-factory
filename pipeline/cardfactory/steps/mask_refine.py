"""Tighten template masks using the committed frame alpha channel."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter


def refine_mask_with_frame_hole(
    mask: Image.Image,
    frame_rgba: Image.Image,
    *,
    hole_alpha_threshold: int = 48,
) -> Image.Image:
    """Intersect ``mask`` with the frame window (transparent hull only).

    Template regions are axis-aligned rectangles; the real frame hole is defined
    by alpha. Zero out mask pixels where the frame is opaque chrome so inpaint /
    illustration never targets filigree the compositor will stamp anyway.
    """
    m = mask.convert("L")
    fr = frame_rgba.convert("RGBA")
    if fr.size != m.size:
        fr = fr.resize(m.size, Image.LANCZOS)
    alpha = fr.split()[3]
    hole = alpha.point(lambda a: 255 if a <= hole_alpha_threshold else 0)
    refined_l = Image.composite(m, Image.new("L", m.size, 0), hole)
    return Image.merge(
        "RGBA",
        (refined_l, refined_l, refined_l, Image.new("L", m.size, 255)),
    )


def refine_m_art_with_frame_hole(
    m_art: Image.Image,
    frame_rgba: Image.Image,
    *,
    hole_alpha_threshold: int = 48,
) -> Image.Image:
    """Keep ``m_art`` only where the frame is visually transparent (the window).

    Layout ``m_art`` is a perfect rectangle; the real PNG hole may be smaller or
    offset by inner border pixels. Intersecting with frame alpha avoids painting
    over ornamental inner rim pixels and reduces rectangular “sticker” edges.
    """
    return refine_mask_with_frame_hole(
        m_art, frame_rgba, hole_alpha_threshold=hole_alpha_threshold
    )


def inset_mask_px(mask: Image.Image, *, px: int) -> Image.Image:
    """Erode a binary RGBA mask inward by ``px`` pixels.

    Uses a min-filter over a ``2*px+1`` square neighbourhood, which shrinks the
    white region by approximately ``px`` pixels on each side.  Returns RGBA with
    the same channel layout as :func:`build_interior_window_edit_mask`.
    """
    if px <= 0:
        return mask.copy()
    size = max(3, 2 * px + 1)
    eroded = mask.convert("L").filter(ImageFilter.MinFilter(size=size))
    return Image.merge("RGBA", (eroded, eroded, eroded, Image.new("L", mask.size, 255)))


def build_interior_window_edit_mask(
    canvas: tuple[int, int],
    inner_rect: dict,
    frame_rgba: Image.Image,
    *,
    hole_alpha_threshold: int = 48,
) -> Image.Image:
    """Single continuous edit region: full inner hull rectangle ∩ frame hole.

    Template ``m_art`` ∪ ``m_stats`` often matches this for two-band layouts, but
    using the hull explicitly avoids accidental one-pixel gaps between bands and
    keeps the inpaint hint and mask from implying two separate stickers.
    """
    w, h = canvas
    ix = int(inner_rect["x"])
    iy = int(inner_rect["y"])
    iw = int(inner_rect["w"])
    ih = int(inner_rect["h"])
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    if iw <= 0 or ih <= 0:
        return img
    rect = (ix, iy, ix + iw - 1, iy + ih - 1)
    draw = ImageDraw.Draw(img)
    draw.rectangle(rect, fill=(255, 255, 255, 255))
    return refine_mask_with_frame_hole(
        img,
        frame_rgba,
        hole_alpha_threshold=hole_alpha_threshold,
    )

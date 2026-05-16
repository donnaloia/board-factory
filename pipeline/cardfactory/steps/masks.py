"""Mask rasterization for Card Factory pipeline steps.

All masks are returned as RGBA PIL images at the full card canvas size.
White (fully opaque) pixels indicate the active region for that mask;
black/transparent pixels are excluded.
"""

from __future__ import annotations

import hashlib

from PIL import Image, ImageChops, ImageDraw


# ────────────────────────── inner-hull helpers ──────────────────────────


def _hull_to_pixel_rect(inner_rect: dict, layout_region: dict) -> tuple[int, int, int, int]:
    """Map a normalized layout region to pixel coordinates inside the inner hull.

    ``inner_rect`` — {x, y, w, h} pixel bounding box of the hull.
    ``layout_region`` — {x, y, width, height} normalized fractions (0..1) relative
    to the inner hull.

    Returns (left, top, right, bottom) with **inclusive** right/bottom edges, suitable
    for :meth:`PIL.ImageDraw.ImageDraw.rectangle` in Pillow ≥ 11.3 (inclusive box).
    """
    ix, iy, iw, ih = (
        inner_rect["x"],
        inner_rect["y"],
        inner_rect["w"],
        inner_rect["h"],
    )
    rx = layout_region["x"]
    ry = layout_region["y"]
    rw = layout_region["width"]
    rh = layout_region["height"]

    left = ix + round(rx * iw)
    top = iy + round(ry * ih)
    width_px = max(0, round(rw * iw))
    height_px = max(0, round(rh * ih))
    if width_px == 0 or height_px == 0:
        return (left, top, left - 1, top - 1)
    right = left + width_px - 1
    bottom = top + height_px - 1
    return (left, top, right, bottom)


# ────────────────────────── mask builders ──────────────────────────


def build_m_art(
    canvas: tuple[int, int],
    inner_rect: dict,
    illustration_region: dict,
) -> Image.Image:
    """White mask inside the illustration region, black everywhere else."""
    w, h = canvas
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    rect = _hull_to_pixel_rect(inner_rect, illustration_region)
    draw = ImageDraw.Draw(img)
    draw.rectangle(rect, fill=(255, 255, 255, 255))
    return img


def build_m_stats(
    canvas: tuple[int, int],
    inner_rect: dict,
    stats_region: dict,
) -> Image.Image:
    """White mask inside the procedural-stats region."""
    w, h = canvas
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    rect = _hull_to_pixel_rect(inner_rect, stats_region)
    draw = ImageDraw.Draw(img)
    draw.rectangle(rect, fill=(255, 255, 255, 255))
    return img


def union_edit_mask(m_art: Image.Image, m_stats: Image.Image) -> Image.Image:
    """White RGBA mask where either illustration or stats region is active (per-channel max of L)."""
    u = ImageChops.lighter(m_art.convert("L"), m_stats.convert("L"))
    return Image.merge("RGBA", (u, u, u, u))


def build_m_stats_text(
    canvas: tuple[int, int],
    inner_rect: dict,
    stats_region: dict,
    typography_padding: dict,
) -> Image.Image:
    """White mask for the glyph plate inside the stats band.

    ``typography_padding`` — {top, right, bottom, left} fractions of the
    stats region's own rect (not of the inner hull).
    """
    w, h = canvas
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))

    left, top, right_i, bottom_i = _hull_to_pixel_rect(inner_rect, stats_region)
    sw = right_i - left + 1
    sh = bottom_i - top + 1

    pt = round(sh * typography_padding.get("top", 0))
    pr = round(sw * typography_padding.get("right", 0))
    pb = round(sh * typography_padding.get("bottom", 0))
    pl = round(sw * typography_padding.get("left", 0))

    glyph_rect = (left + pl, top + pt, right_i - pr, bottom_i - pb)
    draw = ImageDraw.Draw(img)
    draw.rectangle(glyph_rect, fill=(255, 255, 255, 255))
    return img


def build_m_chrome_paint(
    canvas: tuple[int, int],
    inner_rect: dict,
    illustration_region: dict,
    stats_region: dict,
    typography_padding: dict,
    *,
    illustration_inner_mat_px: int = 0,
) -> Image.Image:
    """White where chrome may be painted; black in forbidden zones.

    Forbidden zones: illustration aperture ∪ M_stats_text (glyph box).
    Allowed: frame ring (outside inner hull) + stats surround/plaque.

    ``illustration_inner_mat_px`` — if > 0, only an inset version of the illustration aperture
    is forbidden; the outer ring of that width is allowed so the model can paint an inner-border
    mat decoration.
    """
    w, h = canvas
    # Start with full white canvas (everything allowed)
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Zero out illustration aperture (or its inset, leaving room for inner-mat chrome)
    rect_art = _hull_to_pixel_rect(inner_rect, illustration_region)
    if illustration_inner_mat_px > 0:
        inset = _inset_rect(rect_art, illustration_inner_mat_px)
        if inset[0] < inset[2] and inset[1] < inset[3]:
            draw.rectangle(inset, fill=(0, 0, 0, 255))
        else:
            draw.rectangle(rect_art, fill=(0, 0, 0, 255))
    else:
        draw.rectangle(rect_art, fill=(0, 0, 0, 255))

    # Zero out glyph plate (M_stats_text) inside stats band
    left, top, right_i, bottom_i = _hull_to_pixel_rect(inner_rect, stats_region)
    sw = right_i - left + 1
    sh = bottom_i - top + 1
    pt = round(sh * typography_padding.get("top", 0))
    pr = round(sw * typography_padding.get("right", 0))
    pb = round(sh * typography_padding.get("bottom", 0))
    pl = round(sw * typography_padding.get("left", 0))
    glyph_rect = (left + pl, top + pt, right_i - pr, bottom_i - pb)
    draw.rectangle(glyph_rect, fill=(0, 0, 0, 255))

    return img


def mask_hash(mask: Image.Image) -> str:
    """SHA-256 hex digest of the mask's pixel data (reproducibility record)."""
    raw = mask.convert("L").tobytes()
    return hashlib.sha256(raw).hexdigest()


def intersect_rgba_masks(a: Image.Image, b: Image.Image) -> Image.Image:
    """RGBA mask white where **both** ``a`` and ``b`` are bright (per-channel min of L)."""
    from PIL import ImageChops

    out_l = ImageChops.darker(a.convert("L"), b.convert("L"))
    return Image.merge(
        "RGBA",
        (out_l, out_l, out_l, Image.new("L", a.size, 255)),
    )


# ────────────────────────── post-decode hardening ──────────────────────────


def _inset_rect(
    rect: tuple[int, int, int, int], px: int
) -> tuple[int, int, int, int]:
    """Shrink an inclusive (left, top, right, bottom) rect by ``px`` pixels on each side."""
    l, t, r, b = rect
    return (l + px, t + px, r - px, b - px)


def clamp_forbidden_zones(
    img: Image.Image,
    illustration_region_rect: tuple[int, int, int, int],
    stats_text_rect: tuple[int, int, int, int],
    *,
    illustration_inner_mat_px: int = 0,
) -> Image.Image:
    """Force full transparency in forbidden zones after chrome decode (§8.2).

    ``illustration_region_rect`` and ``stats_text_rect`` are (left, top, right, bottom)
    in canvas pixels, **inclusive** on all sides (Pillow ≥ 11.3 ``rectangle``).

    ``illustration_inner_mat_px`` — if > 0, only the inset rect (shrunk by this many pixels)
    is cleared, preserving a thin inner-border ring the model may have generated inside the
    illustration aperture.  The stats glyph plate (``stats_text_rect``) is always fully cleared
    regardless of this setting.
    """
    out = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(out)
    transparent = (0, 0, 0, 0)
    if illustration_inner_mat_px > 0:
        inset = _inset_rect(illustration_region_rect, illustration_inner_mat_px)
        if inset[0] < inset[2] and inset[1] < inset[3]:
            draw.rectangle(inset, fill=transparent)
        else:
            draw.rectangle(illustration_region_rect, fill=transparent)
    else:
        draw.rectangle(illustration_region_rect, fill=transparent)
    draw.rectangle(stats_text_rect, fill=transparent)
    return out

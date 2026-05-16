"""Interior window from committed frame alpha — organic shape, not layout rectangles.

We take the transparent connected component seeded inside ``inner_rect`` (bounding box
expanded by padding), optionally erode for a mat, and use that mask for painting and
for hardening chrome PNGs. Layout JSON only supplies the seed + typography math.
"""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageDraw

from .mask_refine import build_interior_window_edit_mask, inset_mask_px


def wipe_pixels_under_l_mask(img: Image.Image, mask_l: Image.Image) -> Image.Image:
    """Where ``mask_l`` is bright, replace with fully transparent pixels."""
    empty = Image.new("RGBA", img.size, (0, 0, 0, 0))
    m = mask_l.convert("L").point(lambda p: 255 if p > 128 else 0)
    return Image.composite(empty, img.convert("RGBA"), m)


def build_organic_hole_masks(
    frame_rgba: Image.Image,
    canvas: tuple[int, int],
    inner_rect: dict,
    *,
    hole_alpha_threshold: int,
    rim_erode_px: int,
    cc_bbox_pad_px: int,
    min_area_px: int,
) -> tuple[Image.Image, Image.Image, bool]:
    """Return ``(m_hole_shell, m_paint, used_rect_fallback)``.

    ``m_hole_shell`` — full seeded transparent component (organic silhouette).
    ``m_paint`` — ``erode(shell)`` so art stays inside the bezel; same as wipe region
    for chrome hardening (clear everything the model should not keep opaque).
    ``used_rect_fallback`` is True when seeding or area checks failed and rectangular
    inner-hull masks were used instead.
    """
    fr = frame_rgba.convert("RGBA")
    cw, ch = canvas
    if fr.size != (cw, ch):
        fr = fr.resize((cw, ch), Image.LANCZOS)
    w, h = cw, ch
    alpha = fr.split()[3].tobytes()
    n = w * h
    grid = bytearray(n)
    for i in range(n):
        grid[i] = 1 if alpha[i] <= hole_alpha_threshold else 0

    ix, iy = int(inner_rect["x"]), int(inner_rect["y"])
    iw, ih = int(inner_rect["w"]), int(inner_rect["h"])
    x0 = max(0, ix - cc_bbox_pad_px)
    y0 = max(0, iy - cc_bbox_pad_px)
    x1 = min(w, ix + iw + cc_bbox_pad_px)
    y1 = min(h, iy + ih + cc_bbox_pad_px)

    def in_dom(idx: int) -> bool:
        px = idx % w
        py = idx // w
        return x0 <= px < x1 and y0 <= py < y1

    seed_idx: int | None = None
    scx, scy = ix + iw // 2, iy + ih // 2
    if 0 <= scx < w and 0 <= scy < h:
        si = scy * w + scx
        if grid[si]:
            seed_idx = si
    if seed_idx is None:
        for py in range(iy, min(iy + ih, h)):
            for px in range(ix, min(ix + iw, w)):
                si = py * w + px
                if grid[si]:
                    seed_idx = si
                    break
            if seed_idx is not None:
                break
    if seed_idx is None:
        for i in range(n):
            if grid[i]:
                seed_idx = i
                break

    if seed_idx is None:
        o, p = _fallback_rect_hole_masks(
            (w, h), inner_rect, fr, hole_alpha_threshold, rim_erode_px
        )
        return o, p, True

    visited = bytearray(n)
    q: deque[int] = deque([seed_idx])
    visited[seed_idx] = 1
    area = 0
    while q:
        i = q.popleft()
        area += 1
        x = i % w
        y = i // w
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            ni = ny * w + nx
            if visited[ni] or not grid[ni]:
                continue
            if not in_dom(ni):
                continue
            visited[ni] = 1
            q.append(ni)

    if area < min_area_px:
        o, p = _fallback_rect_hole_masks(
            (w, h), inner_rect, fr, hole_alpha_threshold, rim_erode_px
        )
        return o, p, True

    l_shell = Image.new("L", (w, h), 0)
    lpix = l_shell.load()
    for yy in range(h):
        for xx in range(w):
            ii = yy * w + xx
            if visited[ii]:
                lpix[xx, yy] = 255

    m_shell = Image.merge(
        "RGBA",
        (l_shell, l_shell, l_shell, Image.new("L", (w, h), 255)),
    )
    if rim_erode_px > 0:
        m_paint = inset_mask_px(m_shell, px=rim_erode_px)
    else:
        m_paint = m_shell.copy()
    return m_shell, m_paint, False


def _fallback_rect_hole_masks(
    canvas: tuple[int, int],
    inner_rect: dict,
    fr: Image.Image,
    hole_thr: int,
    rim_erode_px: int,
) -> tuple[Image.Image, Image.Image]:
    outer = build_interior_window_edit_mask(
        canvas, inner_rect, fr, hole_alpha_threshold=hole_thr
    )
    inner = (
        inset_mask_px(outer, px=rim_erode_px)
        if rim_erode_px > 0
        else outer.copy()
    )
    return outer, inner


def harden_chrome_frame_png(
    img: Image.Image,
    canvas: tuple[int, int],
    inner_rect: dict,
    stats_text_rect: tuple[int, int, int, int],
    *,
    hole_alpha_threshold: int,
    rim_erode_px: int,
    cc_bbox_pad_px: int,
    min_area_px: int,
) -> Image.Image:
    """After rectangular pre-clamp, wipe organic interior + glyph plate again.

    ``stats_text_rect`` is (left, top, right, bottom) inclusive for Pillow ``rectangle``.
    """
    out = img.convert("RGBA")
    if out.size != canvas:
        out = out.resize(canvas, Image.LANCZOS)
    _, m_paint, _ = build_organic_hole_masks(
        out,
        canvas,
        inner_rect,
        hole_alpha_threshold=hole_alpha_threshold,
        rim_erode_px=rim_erode_px,
        cc_bbox_pad_px=cc_bbox_pad_px,
        min_area_px=min_area_px,
    )
    out = wipe_pixels_under_l_mask(out, m_paint.convert("L"))
    draw = ImageDraw.Draw(out)
    draw.rectangle(stats_text_rect, fill=(0, 0, 0, 0))
    return out

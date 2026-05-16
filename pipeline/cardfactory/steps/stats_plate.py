"""Stats band fill derived from the frame so chrome remains visible."""

from __future__ import annotations

from PIL import Image


def average_opaque_frame_rgb_under_mask(
    frame: Image.Image,
    canvas: tuple[int, int],
    mask: Image.Image,
) -> tuple[int, int, int]:
    """Mean RGB of opaque frame pixels where ``mask`` luminance > 128.

    Falls back to a warm neutral when no samples are found.
    """
    w, h = canvas
    fr = frame.convert("RGBA")
    if fr.size != (w, h):
        fr = fr.resize((w, h), Image.LANCZOS)
    ml = mask.convert("L")
    bbox = ml.getbbox()
    if bbox is None:
        return (40, 35, 30)

    r_sum, g_sum, b_sum, n = 0, 0, 0, 0
    px = fr.load()
    mload = ml.load()
    x0, y0, x1, y1 = bbox
    for y in range(y0, y1):
        for x in range(x0, x1):
            if mload[x, y] > 128:
                rr, gg, bb, aa = px[x, y]
                if aa > 0:
                    r_sum += rr
                    g_sum += gg
                    b_sum += bb
                    n += 1

    if n == 0:
        return (40, 35, 30)
    return (r_sum // n, g_sum // n, b_sum // n)


def average_rgb_from_rgba_under_mask(
    img: Image.Image,
    canvas: tuple[int, int],
    mask: Image.Image,
) -> tuple[int, int, int] | None:
    """Mean RGB where ``mask`` is bright and pixel alpha > 128.  None if no samples."""
    w, h = canvas
    im = img.convert("RGBA")
    if im.size != (w, h):
        im = im.resize((w, h), Image.LANCZOS)
    ml = mask.convert("L")
    bbox = ml.getbbox()
    if bbox is None:
        return None
    r_sum, g_sum, b_sum, n = 0, 0, 0, 0
    px = im.load()
    mload = ml.load()
    x0, y0, x1, y1 = bbox
    for y in range(y0, y1):
        for x in range(x0, x1):
            if mload[x, y] > 128:
                rr, gg, bb, aa = px[x, y]
                if aa > 128:
                    r_sum += rr
                    g_sum += gg
                    b_sum += bb
                    n += 1
    if n == 0:
        return None
    return (r_sum // n, g_sum // n, b_sum // n)


def ensure_min_luminance_rgb(
    rgb: tuple[int, int, int],
    *,
    min_sum: int = 168,
) -> tuple[int, int, int]:
    """Lift near-black colours so flat mat fills never read as a harsh 'outline'."""
    r, g, b = rgb
    s = r + g + b
    if s >= min_sum:
        return rgb
    if s < 1:
        return (196, 184, 172)
    add = max(1, (min_sum - s + 2) // 3)
    return (
        min(255, r + add),
        min(255, g + add),
        min(255, b + add),
    )


def single_pass_ring_mat_rgb(
    frame: Image.Image,
    painted: Image.Image,
    canvas: tuple[int, int],
    ring_mask: Image.Image,
) -> tuple[int, int, int]:
    """Mat colour for the shell−paint ring: blend frame + painted interior, lift shadows.

    The ring sits on the inner bezel; sampling only the frame there skews very dark
    (chocolate rim) and reads as a black rectangle around the art.
    """
    frame_avg = average_opaque_frame_rgb_under_mask(frame, canvas, ring_mask)
    paint_avg = average_rgb_from_rgba_under_mask(painted, canvas, ring_mask)
    if paint_avg is not None:
        r = int(0.32 * frame_avg[0] + 0.68 * paint_avg[0])
        g = int(0.32 * frame_avg[1] + 0.68 * paint_avg[1])
        b = int(0.32 * frame_avg[2] + 0.68 * paint_avg[2])
        rgb = (r, g, b)
    else:
        rgb = frame_avg
    return ensure_min_luminance_rgb(rgb, min_sum=168)


def stats_background_from_frame(
    frame: Image.Image,
    canvas: tuple[int, int],
    m_stats: Image.Image,
    *,
    alpha: int,
) -> Image.Image:
    """Tint from average frame colour under ``m_stats``, translucent plate.

    Lighter than a flat slab so pixel-art plaque detail still reads through.
    """
    w, h = canvas
    rgb = average_opaque_frame_rgb_under_mask(frame, canvas, m_stats)
    # Darken slightly for glyph contrast; keep warmth from frame
    r, g, b = rgb
    r, g, b = max(0, r - 20), max(0, g - 20), max(0, b - 20)
    return Image.new("RGBA", (w, h), (r, g, b, min(255, max(0, alpha))))

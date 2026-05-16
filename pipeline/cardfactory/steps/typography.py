"""Procedural typography — draw stat lines into the stats band (§8, step 7).

Uses PIL's built-in bitmap font (``ImageFont.load_default``) for
portability. A nicer font can be injected via ``font_path`` without
changing the calling convention.

Text is always drawn inside the glyph plate (M_stats_text) so readability
is guaranteed regardless of what the AI generated in the stats band.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


_DEFAULT_FONT_SIZE = 48
_DEFAULT_TEXT_COLOR = (240, 230, 215, 255)  # warm off-white
_DEFAULT_STROKE_COLOR = (20, 15, 10, 200)   # near-black stroke for contrast


def draw_stat_lines(
    canvas: tuple[int, int],
    stat_lines: list[str],
    *,
    stats_text_rect: tuple[int, int, int, int],
    font_size: int = _DEFAULT_FONT_SIZE,
    font_path: str | None = None,
    text_color: tuple[int, int, int, int] = _DEFAULT_TEXT_COLOR,
    stroke_color: tuple[int, int, int, int] = _DEFAULT_STROKE_COLOR,
    h_align: str = "center",
    v_align: str = "center",
) -> Image.Image:
    """Render ``stat_lines`` into an RGBA layer over the glyph plate.

    Returns a transparent canvas-sized RGBA image with text painted inside
    ``stats_text_rect`` (left, top, right, bottom in canvas pixels).
    Callers composite this layer on top of the stats background.
    """
    w, h = canvas
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    if not stat_lines:
        return layer

    draw = ImageDraw.Draw(layer)

    try:
        font = (
            ImageFont.truetype(font_path, font_size)
            if font_path
            else ImageFont.load_default(size=font_size)
        )
    except (OSError, AttributeError):
        font = ImageFont.load_default()

    left, top, right, bottom = stats_text_rect
    box_w = right - left
    box_h = bottom - top

    if box_w <= 0 or box_h <= 0:
        return layer

    # Measure total text block height
    line_height = font_size + max(4, font_size // 6)
    total_text_h = line_height * len(stat_lines)

    # Vertical starting position
    if v_align == "center":
        y = top + (box_h - total_text_h) // 2
    elif v_align == "bottom":
        y = bottom - total_text_h
    else:
        y = top

    for line in stat_lines:
        if not line:
            y += line_height
            continue

        # Horizontal position
        try:
            bbox = font.getbbox(line)
            text_w = bbox[2] - bbox[0]
        except AttributeError:
            text_w = len(line) * (font_size // 2)

        if h_align == "center":
            x = left + (box_w - text_w) // 2
        elif h_align == "right":
            x = right - text_w
        else:
            x = left

        # Draw stroke then text for legibility
        stroke_width = max(1, font_size // 14)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=stroke_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        draw.text((x, y), line, font=font, fill=text_color)

        y += line_height

    return layer

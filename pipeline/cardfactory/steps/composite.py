"""Layer compositing for full-card assembly (§8, step 8).

Layer order bottom → top:
  1. blank plate (transparent base)
  2. illustration (masked to M_art)
  3. stats background (flat fill or gradient in M_stats)
  4. typography (drawn separately by typography.py before this call)
  5. committed frame PNG (on top — wins at edges)
"""

from __future__ import annotations

from PIL import Image, ImageChops

from .mask_refine import inset_mask_px


def layer_composite(
    *,
    canvas: tuple[int, int],
    illustration: Image.Image,
    m_art: Image.Image,
    stats_background: Image.Image,
    m_stats: Image.Image,
    frame_png: Image.Image,
    typography_layer: Image.Image | None = None,
    chrome_alpha_threshold: int = 48,
) -> Image.Image:
    """Merge all layers into the final card image.

    All inputs must be RGBA at ``canvas`` size.
    ``frame_png`` is composited last so it always wins at the edges, then
    :func:`apply_committed_frame_authority` hard-stamps opaque chrome so soft
    alpha rims do not blend illustration through filigree.
    """
    w, h = canvas

    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # ── layer 2: illustration clipped to M_art ──
    art_clip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    art_clip.paste(illustration, mask=m_art.convert("L"))
    result = Image.alpha_composite(result, art_clip)

    # ── layer 3: stats background clipped to M_stats ──
    stats_clip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    stats_clip.paste(stats_background, mask=m_stats.convert("L"))
    result = Image.alpha_composite(result, stats_clip)

    # ── layer 4: typography overlay (pre-composited by typography.py) ──
    if typography_layer is not None:
        result = Image.alpha_composite(result, typography_layer)

    # ── layer 5: committed frame — always on top ──
    result = Image.alpha_composite(result, frame_png.convert("RGBA"))

    return apply_committed_frame_authority(
        result, frame_png, chrome_alpha_threshold=chrome_alpha_threshold
    )


def apply_committed_frame_authority(
    card: Image.Image,
    frame_png: Image.Image,
    *,
    chrome_alpha_threshold: int = 48,
) -> Image.Image:
    """Alpha-composite the committed frame over the card in all chrome regions.

    ``Image.composite(f, c, stamp)`` would return ``f``'s pixel as-is — including its
    original (low) alpha — so semi-transparent rim pixels (e.g. alpha=40) appear at
    alpha=40 in the final PNG and read as nearly transparent / dark over any display
    background. Instead we paint the frame's chrome onto a transparent layer and then
    alpha-composite that layer over the already-opaque card so rim pixels blend correctly
    (fully opaque result, correct tint) rather than becoming semi-transparent holes.
    """
    c = card.convert("RGBA")
    f = frame_png.convert("RGBA")
    if c.size != f.size:
        f = f.resize(c.size, Image.LANCZOS)
    fa = f.split()[3]
    stamp = fa.point(lambda a: 255 if a > chrome_alpha_threshold else 0)
    chrome_only = Image.new("RGBA", c.size, (0, 0, 0, 0))
    chrome_only.paste(f, mask=stamp)
    return Image.alpha_composite(c, chrome_only)


def alpha_composite_typography(
    base: Image.Image,
    typography_layer: Image.Image | None,
) -> Image.Image:
    """Apply stat glyphs above ``base`` (interior art underlay; frame composited after)."""
    if typography_layer is None:
        return base.convert("RGBA")
    return Image.alpha_composite(base.convert("RGBA"), typography_layer.convert("RGBA"))


def blend_single_pass_under_frame_holes(
    painted: Image.Image,
    frame_png: Image.Image,
    m_integrated: Image.Image,
) -> Image.Image:
    """Legacy hybrid: model pixels in-mask, ``frame_png`` elsewhere.

    Prefer :func:`build_single_pass_art_layer` + ``alpha_composite(art, frame)`` so the
    frame is always a true overlay on top of interior art (professional stack).
    """
    return Image.composite(
        painted.convert("RGBA"),
        frame_png.convert("RGBA"),
        m_integrated.convert("L"),
    )


def build_single_pass_art_layer(
    canvas: tuple[int, int],
    painted: Image.Image,
    m_paint: Image.Image,
) -> Image.Image:
    """Interior-only art layer: transparent outside the edit mask.

    The committed frame is composited on top separately so chrome always wins and
    holes in the frame reveal this layer — same stack as legacy ``layer_composite``.
    """
    w, h = canvas
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.paste(painted.convert("RGBA"), mask=m_paint.convert("L"))
    return layer


def apply_paint_mask_edge_strip(
    card: Image.Image,
    m_paint: Image.Image,
    mat_color: tuple[int, int, int],
    strip_px: int,
) -> Image.Image:
    """Replace the outer ``strip_px`` band of ``m_paint`` with opaque ``mat_color``."""
    if strip_px <= 0:
        return card.convert("RGBA")
    c = card.convert("RGBA")
    inner = inset_mask_px(m_paint, px=strip_px)
    strip_l = ImageChops.subtract(m_paint.convert("L"), inner.convert("L"))
    if not strip_l.getbbox():
        return c
    fill = Image.new("RGBA", c.size, (*mat_color, 255))
    c.paste(fill, mask=strip_l)
    return c


def seal_single_pass_with_frame_on_top(
    interior_pinned: Image.Image,
    frame_png: Image.Image,
    typography_layer: Image.Image | None,
    *,
    chrome_alpha_threshold: int = 48,
) -> Image.Image:
    """Typo on interior art underlay, then committed frame on top; chrome authority last."""
    over_typo = alpha_composite_typography(interior_pinned, typography_layer)
    merged = Image.alpha_composite(over_typo.convert("RGBA"), frame_png.convert("RGBA"))
    return apply_committed_frame_authority(
        merged, frame_png, chrome_alpha_threshold=chrome_alpha_threshold
    )


def apply_art_mat_fill(
    card: Image.Image,
    frame_png: Image.Image,
    m_integrated: Image.Image,
    m_integrated_inset: Image.Image,
    mat_color: tuple[int, int, int],
) -> Image.Image:
    """Fill the ring between ``m_integrated`` and ``m_integrated_inset`` with ``mat_color``.

    The ring is the thin strip just inside the frame hole that was not given to the model
    (model only painted inside ``m_integrated_inset``).  Filling it with a frame-sampled
    colour creates a visual mat between the art rectangle and the frame chrome, eliminating
    the "sticker on frame" appearance for existing committed frames that have rectangular holes.
    """
    c = card.convert("RGBA")
    outer_l = m_integrated.convert("L")
    inner_l = m_integrated_inset.convert("L")
    ring_l = ImageChops.subtract(outer_l, inner_l)
    if not ring_l.getbbox():
        return c
    mat_fill = Image.new("RGBA", c.size, (*mat_color, 255))
    c.paste(mat_fill, mask=ring_l)
    return c


def flat_stats_background(
    canvas: tuple[int, int],
    color: tuple[int, int, int, int] = (40, 35, 30, 220),
) -> Image.Image:
    """Solid-color fill layer for the stats band (tests + simple variant).

    ``alpha`` in ``color`` defaults high for legacy tests; production prefers
    :func:`stats_plate.stats_background_from_frame`.
    """
    return Image.new("RGBA", canvas, color)

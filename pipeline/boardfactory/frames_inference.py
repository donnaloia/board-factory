"""Deterministic post-processing for frame-extraction proposals.

The vision step (Phase A in the customization plan) returns soft, noisy
candidate masks. Before we hand a candidate to the user as a refinable
``FrameInstance``, we run it through the math here:

  - threshold        — float / soft mask -> binary mask
  - morphological close — fills 1-2 px gaps in the rim contour
  - grid snap        — snap bbox edges to multiples of the source's pixel grid
  - mask -> nine slice — derive (hole, rim) and a ``ring_px`` heuristic from
                         the bbox so today's compositor still works

Keeping this code out of any specific provider keeps the providers small
and means we can swap GPT-image for SAM2 / Replicate without rewriting
the geometry path. Tests live in ``app/tests/test_frames_inference.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from . import frames as bf_frames


# ────────────────────────── data shape ──────────────────────────


@dataclass(frozen=True)
class CandidateGeometry:
    """A clean candidate ready for the user: bbox + masks + ring estimate."""

    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2) in source-asset pixels
    ring_px: int                      # average rim thickness, source pixels
    hole_mask: Image.Image            # L-mode binary, source-asset size
    rim_mask: Image.Image             # L-mode binary, source-asset size
    score: float                      # 0..1, model-reported (or 1.0 for deterministic)
    notes: str = ""

    def to_dict(self) -> dict:
        x1, y1, x2, y2 = self.bbox
        return {
            "bbox": [x1, y1, x2, y2],
            "ring_px": self.ring_px,
            "score": self.score,
            "notes": self.notes,
        }


# ────────────────────────── primitives ──────────────────────────


def threshold(mask: Image.Image, *, level: int = 128) -> Image.Image:
    """Binarize an L-mode mask at ``level`` (default 128)."""
    return mask.convert("L").point(lambda v: 255 if v >= level else 0)


def morph_close(mask: Image.Image, *, radius: int = 2) -> Image.Image:
    """Dilation followed by erosion — fills small gaps in the rim contour.

    PIL's MaxFilter / MinFilter handle the per-pixel work without us
    pulling in scipy. ``radius`` is in source pixels; 2 is a good default
    for a 256-512 source asset. Larger radii start fusing the rim with
    nearby ornament inside the panel, which is bad.
    """
    if radius <= 0:
        return mask
    size = radius * 2 + 1
    dilated = mask.filter(ImageFilter.MaxFilter(size))
    return dilated.filter(ImageFilter.MinFilter(size))


def bbox_of(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Tightest bounding box of the white region. ``None`` if the mask is empty."""
    return mask.getbbox()


def hole_area_fraction(hole: Image.Image, source_size: tuple[int, int]) -> float:
    """Fraction of the canvas covered by white in ``hole``."""
    w, h = source_size
    if w <= 0 or h <= 0:
        return 0.0
    data = hole.convert("L").getdata()
    white = sum(1 for v in data if v >= 128)
    return white / float(w * h)


def bbox_area_fraction(
    bbox: tuple[int, int, int, int],
    source_size: tuple[int, int],
) -> float:
    """Fraction of the image plane covered by an axis-aligned bbox."""
    sw, sh = source_size
    if sw <= 0 or sh <= 0:
        return 0.0
    x1, y1, x2, y2 = bbox
    aw = max(0, x2 - x1)
    ah = max(0, y2 - y1)
    return (aw * ah) / float(sw * sh)


def grid_snap_bbox(
    bbox: tuple[int, int, int, int],
    *,
    grid: int = 1,
    image_size: tuple[int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Round bbox edges to the nearest multiple of ``grid``.

    ``grid`` is in source pixels. For pixel-art boards the native scale
    is usually >1 (a "logical pixel" is 4x4 image pixels); pass that
    scale here so corners land on grid intersections. Output is clipped
    to ``image_size`` when provided.
    """
    if grid <= 1:
        x1, y1, x2, y2 = bbox
        return int(x1), int(y1), int(x2), int(y2)
    x1, y1, x2, y2 = bbox

    def _snap(v: float, *, up: bool) -> int:
        steps = v / grid
        return int((steps + (0.5 if up else 0.0)) // 1) * grid

    x1s = _snap(x1, up=False)
    y1s = _snap(y1, up=False)
    # Round outward at the bottom-right edge so we never cut into the rim.
    x2s = _snap(x2 + (grid - 1), up=False)
    y2s = _snap(y2 + (grid - 1), up=False)

    if image_size is not None:
        w, h = image_size
        x1s = max(0, min(w, x1s))
        y1s = max(0, min(h, y1s))
        x2s = max(0, min(w, x2s))
        y2s = max(0, min(h, y2s))
    if x2s <= x1s or y2s <= y1s:
        # Snapping collapsed the bbox; fall back to unsnapped.
        return int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    return x1s, y1s, x2s, y2s


def ring_thickness(rim: Image.Image) -> int:
    """Average rim thickness across the four sides of ``rim``.

    Computed as the mean width of the white region along the top edge
    plus the mean height along the left edge. For a uniform ring this
    equals the ring thickness; for a tapered rim it averages the four
    sides into a single number that the slider can show.
    """
    rim_l = rim.convert("L")
    w, h = rim_l.size
    if w == 0 or h == 0:
        return 0

    def _mean_run(line: list[int]) -> float:
        runs: list[int] = []
        run = 0
        for v in line:
            if v >= 128:
                run += 1
            elif run > 0:
                runs.append(run)
                run = 0
        if run > 0:
            runs.append(run)
        return (sum(runs) / len(runs)) if runs else 0.0

    # Sample four representative scan lines (1/4, 1/2 across each axis).
    samples: list[float] = []
    for y in (h // 4, h * 3 // 4):
        if 0 <= y < h:
            row = [rim_l.getpixel((x, y)) for x in range(w)]
            samples.append(_mean_run(row))
    for x in (w // 4, w * 3 // 4):
        if 0 <= x < w:
            col = [rim_l.getpixel((x, y)) for y in range(h)]
            samples.append(_mean_run(col))
    samples = [s for s in samples if s > 0]
    if not samples:
        return 0
    return max(1, int(round(sum(samples) / len(samples))))


# ────────────────────────── pipeline ──────────────────────────


def candidate_from_outer_inner(
    *,
    source_size: tuple[int, int],
    outer: Image.Image,
    inner: Image.Image,
    score: float = 1.0,
    notes: str = "",
    morph_radius: int = 2,
    grid: int = 1,
    hole_expand_px: int | None = None,
) -> CandidateGeometry:
    """Run cleanup on a model's (outer, inner) pair and return a candidate.

    The contract is:

      outer = boolean mask of (rim + hole)
      inner = boolean mask of (hole only)

    These are the most natural shape for a vision model to return; we
    stay agnostic to whether the model produced them as polygons or as
    a single mask cleaved by a ring detector. Both paths converge here.

    ``hole_expand_px`` dilates the hole within ``outer`` so mis-tagged legacy
    chrome is less likely to remain in the rim band. When ``None``, reads
    ``BOARDFACTORY_FRAME_HOLE_EXPAND_PROPOSE_PX`` (default ``1``).
    """
    if hole_expand_px is None:
        try:
            hole_expand_px = max(
                0, int(os.environ.get("BOARDFACTORY_FRAME_HOLE_EXPAND_PROPOSE_PX", "1")),
            )
        except ValueError:
            hole_expand_px = 1

    o = morph_close(threshold(outer), radius=morph_radius)
    i = morph_close(threshold(inner), radius=morph_radius)
    hole, rim = bf_frames.derive_masks_from_segmentation(source_size, o, i)
    if hole_expand_px > 0:
        hole = bf_frames.expand_hole_within_outer(hole, o, hole_expand_px)
        rim = ImageChops.subtract(o, hole.convert("L"))

    cov = hole_area_fraction(hole, source_size)
    note_suffix = ""
    if cov < 0.08:
        note_suffix = (
            " · warning: hole covers <8% of tile — inner polygon may hug subject "
            "instead of full aperture"
        )

    bb = bbox_of(o) or (0, 0, *source_size)
    bb = grid_snap_bbox(bb, grid=grid, image_size=source_size)
    rp = ring_thickness(rim)
    combined_notes = (notes + note_suffix).strip()
    return CandidateGeometry(
        bbox=bb,
        ring_px=rp,
        hole_mask=hole,
        rim_mask=rim,
        score=float(score),
        notes=combined_notes,
    )


def candidate_from_ring(
    *,
    source_size: tuple[int, int],
    ring_px: int,
    score: float = 1.0,
    notes: str = "",
    grid: int = 1,
) -> CandidateGeometry:
    """Build a candidate from today's deterministic ``ring_px`` shortcut.

    Used as the fallback when vision is unavailable (no API key) or when
    the user explicitly chooses the deterministic path from the Atelier.
    """
    hole, rim = bf_frames.derive_masks_from_ring(source_size, ring_px)
    w, h = source_size
    bb = grid_snap_bbox((0, 0, w, h), grid=grid, image_size=source_size)
    return CandidateGeometry(
        bbox=bb,
        ring_px=ring_px,
        hole_mask=hole,
        rim_mask=rim,
        score=float(score),
        notes=notes or "deterministic 9-slice (no vision)",
    )


def _snap_hole_to_ring_target(
    hole: Image.Image,
    outer: Image.Image,
    target_rp: int,
    *,
    max_iter: int = 48,
) -> Image.Image:
    """Grow/shrink the hole mask so ``ring_thickness(subtract(outer, hole))`` ≈ ``target_rp``.

    Used after bbox-clipping vision masks so the ring slider still adjusts apparent
    rim thickness without replacing masks with axis-aligned rectangles.
    """
    from PIL import ImageChops, ImageFilter  # noqa: PLC0415

    h = hole.convert("L")
    outer_l = outer.convert("L")
    target_rp = max(2, int(target_rp))

    for _ in range(max_iter):
        rim = ImageChops.subtract(outer_l, h)
        rt = ring_thickness(rim)
        if rt <= 0:
            break
        if abs(rt - target_rp) <= 1:
            break
        if rt > target_rp:
            # Rim too wide → enlarge hole (dilate white region).
            h = h.filter(ImageFilter.MaxFilter(3))
            h = ImageChops.multiply(h, outer_l)
        else:
            # Rim too thin → shrink hole (erode).
            h = h.filter(ImageFilter.MinFilter(3))
            h = ImageChops.multiply(h, outer_l)
        if bbox_of(h) is None:
            break
    return h


def fit_to_window(
    candidate: CandidateGeometry,
    *,
    bbox: tuple[int, int, int, int],
    source_size: tuple[int, int],
    morph_radius: int = 1,
) -> CandidateGeometry:
    """Apply a user-edited bbox (and target ring thickness) to a candidate.

    Vision proposals carry **non-rectangular** hole/rim masks. We clip those masks
    to the draggable bbox instead of replacing them with plain rectangles — that
    preserves AI-identified frame contours through refine.

    Ring thickness from ``candidate.ring_px`` is approximated by morphologically
    adjusting the clipped hole until the measured rim strip matches.
    """
    from PIL import ImageChops, ImageDraw  # noqa: PLC0415

    w, h = source_size
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(w - 1, int(x1)))
    y1 = max(0, min(h - 1, int(y1)))
    x2 = max(x1 + 2, min(w, int(x2)))
    y2 = max(y1 + 2, min(h, int(y2)))

    bbox_layer = Image.new("L", (w, h), 0)
    ImageDraw.Draw(bbox_layer).rectangle((x1, y1, x2 - 1, y2 - 1), fill=255)

    ho = candidate.hole_mask.convert("L")
    ri = candidate.rim_mask.convert("L")
    hole_clip = ImageChops.multiply(ho, bbox_layer)
    rim_clip = ImageChops.multiply(ri, bbox_layer)
    outer_clip = ImageChops.lighter(hole_clip, rim_clip)

    target_rp = candidate.ring_px or max(2, min(x2 - x1, y2 - y1) // 16)
    target_rp = max(2, min(target_rp, min(x2 - x1, y2 - y1) // 2 - 1))

    hole_adj = _snap_hole_to_ring_target(hole_clip, outer_clip, target_rp)

    return candidate_from_outer_inner(
        source_size=source_size,
        outer=outer_clip,
        inner=hole_adj,
        score=candidate.score,
        notes=(candidate.notes + " · refined").strip(),
        morph_radius=morph_radius,
        grid=1,
        hole_expand_px=0,
    )


# ────────────────────────── debug / preview helpers ──────────────────────────


def overlay_for_review(
    source: Image.Image,
    rim: Image.Image,
    hole: Image.Image,
    *,
    rim_color: tuple[int, int, int, int] = (255, 80, 200, 160),
    hole_color: tuple[int, int, int, int] = (40, 180, 255, 90),
) -> Image.Image:
    """Paint the rim + hole masks over ``source`` for the Atelier preview.

    The tinted overlay is what makes "rim vs hole" obvious in the UI
    without asking the user to imagine where the ring sits. The colors
    are intentionally noisy so they read against any palette.
    """
    base = source.convert("RGBA")
    if base.size != rim.size:
        rim = rim.resize(base.size, Image.NEAREST)
    if base.size != hole.size:
        hole = hole.resize(base.size, Image.NEAREST)

    rim_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    hole_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rim_layer.paste(Image.new("RGBA", base.size, rim_color), (0, 0), rim)
    hole_layer.paste(Image.new("RGBA", base.size, hole_color), (0, 0), hole)
    out = Image.alpha_composite(base, rim_layer)
    out = Image.alpha_composite(out, hole_layer)
    return out


__all__ = [
    "CandidateGeometry",
    "threshold",
    "morph_close",
    "bbox_of",
    "hole_area_fraction",
    "bbox_area_fraction",
    "grid_snap_bbox",
    "ring_thickness",
    "candidate_from_outer_inner",
    "candidate_from_ring",
    "fit_to_window",
    "overlay_for_review",
]

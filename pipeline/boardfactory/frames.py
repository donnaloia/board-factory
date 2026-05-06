"""House frame system — 9-slice ornate frames shared across all functional panels.

A frame is stored on disk as 8 PNG sprites (4 corners + 4 edges) plus a metadata
sidecar. At composite time, the frame is reassembled at any target size by:

  1. Pasting the four corners into the corners of the target rectangle.
  2. Tiling the top/bottom edges horizontally between the corners.
  3. Tiling the left/right edges vertically between the corners.
  4. Leaving the center transparent — that's where the panel interior goes.

Why 9-slice instead of "scale the whole frame"?
  - Pixel art frames lose their pixel grid when bilinearly resized.
  - Scaling a 64×64 corner up to 80×80 makes blurry pixels.
  - Tiling preserves the original pixel discipline; corners stay corners.

The "house frame" lives at workspace/frames/house/ — exactly one frame is
active per board. Per-panel frame overrides are explicitly out of scope.

In addition to the 8 sprite PNGs, the on-disk pack also stores two binary
masks at the source-asset resolution:

  - hole_mask.png   white = interior content area (inpaint here / show through)
  - rim_mask.png    white = decorative rim (preserve / paste this on top)

For a deterministic 9-slice frame these are simple rectangles derived from
``ring_px``; for vision-derived frames they may have non-rectangular
geometry. The compositor uses ``rim_mask`` when present so panel art with
baked-in chrome shows through the hole region instead of being double-framed.
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from . import config


# ────────────────────────── path helpers ──────────────────────────


def frames_root() -> Path:
    return config.WORKSPACE / "frames"


def house_dir() -> Path:
    return frames_root() / "house"


def house_meta_path() -> Path:
    return house_dir() / "frame.json"


def has_house_frame() -> bool:
    """Truthy when a complete house frame has been adopted on this board."""
    d = house_dir()
    if not d.exists() or not house_meta_path().exists():
        return False
    return all((d / f"{name}.png").exists() for name in _SLICE_NAMES)


_SLICE_NAMES = (
    "corner_tl", "corner_tr", "corner_bl", "corner_br",
    "edge_top", "edge_bottom", "edge_left", "edge_right",
)


# ────────────────────────── metadata ──────────────────────────


@dataclass
class FrameInstance:
    """Sidecar metadata for an adopted house frame.

    Carries provenance the Atelier needs (where the rim came from, which
    vision model produced it) plus the geometry parameters that drive
    9-slice composition. Persisted as ``frame.json`` next to the eight
    slice PNGs and the two masks; mirrored into the relational store for
    cross-board queries (see ``app/domains/cells/frames_repository.py``).
    """

    ring_px: int                              # outer ring thickness, source-asset pixels
    source_kind: str                          # "panel" | "mockup" | "upload"
    source_id: str | None                     # panel id, mockup region key, or upload filename
    source_size: tuple[int, int]              # WxH of the source asset frame was cut from
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    notes: str = ""

    # Optional provenance.
    source_cell_id: str | None = None         # cells.id when source was a panel cell
    source_asset_version_id: int | None = None  # asset_versions.id when sourced from history
    model_id: str | None = None               # vision model id (e.g. "gpt-4o-2024-08-06")
    prompt_hash: str | None = None            # short hash of vision prompt for replay
    candidate_index: int | None = None        # which proposal (0-based) the user picked

    def to_dict(self) -> dict:
        d: dict = {
            "ring_px": self.ring_px,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_size": list(self.source_size),
            "created_ms": self.created_ms,
            "notes": self.notes,
        }
        if self.source_cell_id is not None:
            d["source_cell_id"] = self.source_cell_id
        if self.source_asset_version_id is not None:
            d["source_asset_version_id"] = self.source_asset_version_id
        if self.model_id:
            d["model_id"] = self.model_id
        if self.prompt_hash:
            d["prompt_hash"] = self.prompt_hash
        if self.candidate_index is not None:
            d["candidate_index"] = self.candidate_index
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FrameInstance":
        kind = str(d.get("source_kind", "panel"))
        if kind == "mockup_region":
            kind = "mockup"
        if kind == "generated":
            kind = "upload"
        size_raw = d.get("source_size", [0, 0])
        size = (int(size_raw[0]), int(size_raw[1])) if size_raw else (0, 0)
        return cls(
            ring_px=int(d["ring_px"]),
            source_kind=kind,
            source_id=d.get("source_id"),
            source_size=size,
            created_ms=int(d.get("created_ms", 0)),
            notes=str(d.get("notes", "")),
            source_cell_id=d.get("source_cell_id"),
            source_asset_version_id=d.get("source_asset_version_id"),
            model_id=d.get("model_id"),
            prompt_hash=d.get("prompt_hash"),
            candidate_index=d.get("candidate_index"),
        )


# Back-compat alias — older callers used ``FrameMeta``. New code should use
# ``FrameInstance`` directly. Both names map to the same dataclass so a
# pickled instance from one continues to work as the other.
FrameMeta = FrameInstance


def read_house_meta() -> FrameInstance | None:
    p = house_meta_path()
    if not p.exists():
        return None
    try:
        return FrameInstance.from_dict(json.loads(p.read_text()))
    except Exception:
        return None


def write_house_meta(meta: FrameInstance) -> None:
    house_dir().mkdir(parents=True, exist_ok=True)
    house_meta_path().write_text(json.dumps(meta.to_dict(), indent=2))


# ────────────────────────── extraction ──────────────────────────


@dataclass
class NineSlice:
    """In-memory 9-slice (no center sprite — center is transparent).

    ``hole_mask`` and ``rim_mask`` are 1-channel ``L`` images sized to the
    source asset (``source_size``). White = inside that region. They are
    derived deterministically from ``ring_px`` for today's pipeline and
    replaced by vision-extractor output once Phase A wiring is live. They
    are persisted alongside the eight sprite PNGs and used by the
    compositor to avoid double chrome on panels with baked-in frames.
    """

    corner_tl: Image.Image
    corner_tr: Image.Image
    corner_bl: Image.Image
    corner_br: Image.Image
    edge_top: Image.Image     # full strip between top corners (height = ring_px)
    edge_bottom: Image.Image
    edge_left: Image.Image
    edge_right: Image.Image
    ring_px: int
    hole_mask: Image.Image | None = None
    rim_mask: Image.Image | None = None

    def save(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        self.corner_tl.save(dest / "corner_tl.png")
        self.corner_tr.save(dest / "corner_tr.png")
        self.corner_bl.save(dest / "corner_bl.png")
        self.corner_br.save(dest / "corner_br.png")
        self.edge_top.save(dest / "edge_top.png")
        self.edge_bottom.save(dest / "edge_bottom.png")
        self.edge_left.save(dest / "edge_left.png")
        self.edge_right.save(dest / "edge_right.png")
        if self.hole_mask is not None:
            self.hole_mask.save(dest / "hole_mask.png")
        if self.rim_mask is not None:
            self.rim_mask.save(dest / "rim_mask.png")

    @classmethod
    def load(cls, src: Path, ring_px: int) -> "NineSlice":
        hole = None
        rim = None
        hole_p = src / "hole_mask.png"
        rim_p = src / "rim_mask.png"
        if hole_p.exists():
            hole = Image.open(hole_p).convert("L")
        if rim_p.exists():
            rim = Image.open(rim_p).convert("L")
        return cls(
            corner_tl=Image.open(src / "corner_tl.png").convert("RGBA"),
            corner_tr=Image.open(src / "corner_tr.png").convert("RGBA"),
            corner_bl=Image.open(src / "corner_bl.png").convert("RGBA"),
            corner_br=Image.open(src / "corner_br.png").convert("RGBA"),
            edge_top=Image.open(src / "edge_top.png").convert("RGBA"),
            edge_bottom=Image.open(src / "edge_bottom.png").convert("RGBA"),
            edge_left=Image.open(src / "edge_left.png").convert("RGBA"),
            edge_right=Image.open(src / "edge_right.png").convert("RGBA"),
            ring_px=ring_px,
            hole_mask=hole,
            rim_mask=rim,
        )


def extract_9slice(source: Image.Image, ring_px: int) -> NineSlice:
    """Cut a 9-slice from a source raster.

    Layout:
        corner = ring_px × ring_px squares at each corner
        edge_top    = strip from (ring_px, 0) to (W-ring_px, ring_px)
        edge_bottom = strip from (ring_px, H-ring_px) to (W-ring_px, H)
        edge_left   = strip from (0, ring_px) to (ring_px, H-ring_px)
        edge_right  = strip from (W-ring_px, ring_px) to (W, H-ring_px)

    The center is discarded (and will be transparent at composite time).
    Hole / rim masks are derived deterministically from ``ring_px`` so
    this remains a pure function of (image, ring_px) and the on-disk pack
    is self-contained.
    """
    src = source.convert("RGBA")
    w, h = src.size
    if ring_px <= 0 or ring_px * 2 >= min(w, h):
        raise ValueError(
            f"ring_px={ring_px} is invalid for source size {w}×{h} "
            f"(must be > 0 and < min(W,H)/2)"
        )
    rp = ring_px
    hole, rim = derive_masks_from_ring((w, h), rp)
    return NineSlice(
        corner_tl=src.crop((0, 0, rp, rp)),
        corner_tr=src.crop((w - rp, 0, w, rp)),
        corner_bl=src.crop((0, h - rp, rp, h)),
        corner_br=src.crop((w - rp, h - rp, w, h)),
        edge_top=src.crop((rp, 0, w - rp, rp)),
        edge_bottom=src.crop((rp, h - rp, w - rp, h)),
        edge_left=src.crop((0, rp, rp, h - rp)),
        edge_right=src.crop((w - rp, rp, w, h - rp)),
        ring_px=rp,
        hole_mask=hole,
        rim_mask=rim,
    )


def derive_masks_from_ring(
    size: tuple[int, int],
    ring_px: int,
) -> tuple[Image.Image, Image.Image]:
    """Deterministic hole + rim masks for today's nine-slice path.

    Both are L-mode greyscale at ``size``:

      - hole: white inside the rectangle inset by ``ring_px``, black on the rim.
      - rim:  inverse of hole.

    Phase A vision will replace this helper with a non-rectangular variant
    that draws from segmentation polygons. The rest of the pipeline only
    cares about the (hole, rim) pair, so the contract is the same either way.
    """
    w, h = size
    if ring_px < 0 or ring_px * 2 > min(w, h):
        raise ValueError(
            f"ring_px={ring_px} invalid for size {w}×{h} "
            f"(must be 0 ≤ ring_px ≤ min(W,H)/2)"
        )
    hole = Image.new("L", (w, h), 0)
    if ring_px * 2 < min(w, h):
        ImageDraw.Draw(hole).rectangle(
            (ring_px, ring_px, w - ring_px - 1, h - ring_px - 1),
            fill=255,
        )
    # Rim is the inverse of hole.
    rim = Image.eval(hole, lambda v: 255 - v)
    return hole, rim


def derive_masks_from_segmentation(
    size: tuple[int, int],
    outer: Image.Image,
    inner: Image.Image,
) -> tuple[Image.Image, Image.Image]:
    """Build hole + rim masks from a Phase A vision segmentation.

    ``outer`` is the boolean mask for the entire frame (rim ∪ hole).
    ``inner`` is the boolean mask for the content hole only. Both are
    L-mode binary at ``size``. The rim is ``outer & ¬inner``; the hole
    is ``inner``. We threshold and clip rather than trusting the raw
    bytes so a model that returned slightly-soft edges still produces a
    discrete pair of masks.
    """
    w, h = size
    if outer.size != (w, h) or inner.size != (w, h):
        raise ValueError(
            "outer/inner masks must match size; "
            f"got outer={outer.size}, inner={inner.size}, expected={size}"
        )
    o = outer.convert("L").point(lambda v: 255 if v >= 128 else 0)
    i = inner.convert("L").point(lambda v: 255 if v >= 128 else 0)
    hole = i
    # rim = outer AND NOT inner. PIL has no per-pixel logical-and on L
    # images, but ImageChops.subtract gives us (o - i) clipped at 0 which
    # is the same thing for binary inputs.
    from PIL import ImageChops  # noqa: PLC0415 — keep import lazy for module bootup.

    rim = ImageChops.subtract(o, i)
    return hole, rim


# ────────────────────────── composition ──────────────────────────


def compose_frame(slice_: NineSlice, target_size: tuple[int, int]) -> Image.Image:
    """Reassemble the 9-slice at any target size.

    Returns an RGBA image with a transparent center hole the size of
    (W - 2*ring, H - 2*ring). Caller composites this on TOP of the panel
    interior so the interior shows through the hole.

    Edges are tiled, NOT stretched, so pixel discipline is preserved at
    every target size. If target dimensions aren't a clean multiple of the
    edge sprite length, the last tile is cropped — visually invisible at
    pixel-art density.
    """
    tw, th = target_size
    rp = slice_.ring_px
    if tw < 2 * rp or th < 2 * rp:
        raise ValueError(
            f"target {tw}×{th} too small for ring_px={rp} "
            f"(need at least {2*rp}×{2*rp})"
        )

    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))

    out.paste(slice_.corner_tl, (0, 0), slice_.corner_tl)
    out.paste(slice_.corner_tr, (tw - rp, 0), slice_.corner_tr)
    out.paste(slice_.corner_bl, (0, th - rp), slice_.corner_bl)
    out.paste(slice_.corner_br, (tw - rp, th - rp), slice_.corner_br)

    edge_w_run = tw - 2 * rp
    edge_h_run = th - 2 * rp

    _tile_horizontal(out, slice_.edge_top, x_start=rp, y=0, run=edge_w_run)
    _tile_horizontal(out, slice_.edge_bottom, x_start=rp, y=th - rp, run=edge_w_run)
    _tile_vertical(out, slice_.edge_left, x=0, y_start=rp, run=edge_h_run)
    _tile_vertical(out, slice_.edge_right, x=tw - rp, y_start=rp, run=edge_h_run)

    return out


def _tile_horizontal(canvas: Image.Image, sprite: Image.Image,
                     x_start: int, y: int, run: int) -> None:
    if run <= 0:
        return
    sw = sprite.width
    x = x_start
    end = x_start + run
    while x < end:
        chunk = sprite if (end - x) >= sw else sprite.crop((0, 0, end - x, sprite.height))
        canvas.paste(chunk, (x, y), chunk)
        x += sw


def _tile_vertical(canvas: Image.Image, sprite: Image.Image,
                   x: int, y_start: int, run: int) -> None:
    if run <= 0:
        return
    sh = sprite.height
    y = y_start
    end = y_start + run
    while y < end:
        chunk = sprite if (end - y) >= sh else sprite.crop((0, 0, sprite.width, end - y))
        canvas.paste(chunk, (x, y), chunk)
        y += sh


# ────────────────────────── interior masking (for inpainting) ──────────────────────────


def interior_mask(target_size: tuple[int, int], ring_px: int) -> Image.Image:
    """Black-and-white mask: WHITE inside the frame ring (regenerate), BLACK in
    the ring (preserve). PixelLab's inpaint expects this convention.

    Returned as a 1-channel L-mode PNG, not RGBA, since inpainting tools
    typically want a binary mask.
    """
    hole, _rim = derive_masks_from_ring(target_size, ring_px)
    return hole


def interior_mask_bytes(target_size: tuple[int, int], ring_px: int) -> bytes:
    """PNG bytes for interior_mask(). Convenience for provider.inpaint()."""
    m = interior_mask(target_size, ring_px)
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return buf.getvalue()


def hole_mask_for_target(
    slice_: NineSlice,
    target_size: tuple[int, int],
    *,
    source_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Hole mask scaled from source-asset size to a target panel size.

    Falls back to a deterministic ring-derived rectangle when the slice
    has no stored hole mask (older on-disk packs). Vision-derived frames
    carry a non-rectangular hole and that geometry survives the resize.

    ``source_size`` overrides the implicit scale source (e.g. the caller
    passes the FrameInstance.source_size so the ring scales the same way
    ``draw_cell`` does for inpaint).
    """
    src_hole = slice_.hole_mask
    tw, th = target_size
    if src_hole is None:
        # Scale ring proportionally to the smaller dimension to keep ring
        # thickness stable across panel aspect ratios.
        sw, sh = source_size if source_size is not None else (tw, th)
        scale = min(tw / max(sw, 1), th / max(sh, 1))
        scaled_ring = max(1, int(round(slice_.ring_px * scale)))
        hole, _ = derive_masks_from_ring((tw, th), scaled_ring)
        return hole
    return src_hole.resize((tw, th), Image.NEAREST)


# ────────────────────────── on-disk house frame helpers ──────────────────────────


def adopt_house_frame(slice_: NineSlice, meta: FrameInstance) -> None:
    """Replace the active house frame with this 9-slice + metadata.

    If the slice was constructed without explicit hole/rim masks, derive
    them from ``ring_px`` here so every adopted pack always has the full
    on-disk surface (sprites + masks + frame.json). This keeps the
    compositor's "is there a hole mask?" check trivially true after adopt.
    """
    house_dir().mkdir(parents=True, exist_ok=True)
    if slice_.hole_mask is None or slice_.rim_mask is None:
        size = (
            slice_.corner_tl.width + slice_.corner_tr.width + slice_.edge_top.width,
            slice_.corner_tl.height + slice_.corner_bl.height + slice_.edge_left.height,
        )
        hole, rim = derive_masks_from_ring(size, slice_.ring_px)
        slice_.hole_mask = hole
        slice_.rim_mask = rim
    slice_.save(house_dir())
    write_house_meta(meta)


def load_house_frame() -> tuple[NineSlice, FrameInstance] | None:
    """Load the active house frame from disk. Returns None if no frame adopted."""
    if not has_house_frame():
        return None
    meta = read_house_meta()
    if meta is None:
        return None
    slice_ = NineSlice.load(house_dir(), ring_px=meta.ring_px)
    return slice_, meta


def compose_house_frame_for(target_size: tuple[int, int]) -> Image.Image | None:
    """Convenience: load + compose at a target size in one call.

    Returns None when no house frame is adopted on this board (so callers can
    fall back to the no-frame path without raising).
    """
    loaded = load_house_frame()
    if loaded is None:
        return None
    slice_, _ = loaded
    return compose_frame(slice_, target_size)


def compose_house_rim_for(target_size: tuple[int, int]) -> Image.Image | None:
    """Same as ``compose_house_frame_for`` but with the rim mask applied.

    For deterministic 9-slice frames this is bit-identical to
    ``compose_house_frame_for`` (the implicit rim is the corner+edge
    sprites, and the center is already transparent). For Phase A vision
    frames with non-rectangular rims, this clips the composed pixels to
    the stored rim mask so the panel interior shows through wherever the
    rim has cut-outs.

    Returns ``None`` if no house frame is adopted.
    """
    loaded = load_house_frame()
    if loaded is None:
        return None
    slice_, _ = loaded
    composed = compose_frame(slice_, target_size)
    if slice_.rim_mask is None:
        return composed
    rim_resized = slice_.rim_mask.resize(target_size, Image.NEAREST)
    composed.putalpha(rim_resized)
    return composed

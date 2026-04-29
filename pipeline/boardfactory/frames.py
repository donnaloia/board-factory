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
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

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
class FrameMeta:
    """Sidecar metadata for the house frame."""
    ring_px: int                  # outer ring thickness in source-asset pixels
    source_kind: str              # "panel" | "mockup_region" | "generated"
    source_id: str | None         # the panel id or mockup region key
    source_size: tuple[int, int]  # WxH of the source asset that frame was cut from
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "ring_px": self.ring_px,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_size": list(self.source_size),
            "created_ms": self.created_ms,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FrameMeta":
        return cls(
            ring_px=int(d["ring_px"]),
            source_kind=str(d.get("source_kind", "panel")),
            source_id=d.get("source_id"),
            source_size=tuple(d.get("source_size", [0, 0])),
            created_ms=int(d.get("created_ms", 0)),
            notes=str(d.get("notes", "")),
        )


def read_house_meta() -> FrameMeta | None:
    p = house_meta_path()
    if not p.exists():
        return None
    try:
        return FrameMeta.from_dict(json.loads(p.read_text()))
    except Exception:
        return None


def write_house_meta(meta: FrameMeta) -> None:
    house_dir().mkdir(parents=True, exist_ok=True)
    house_meta_path().write_text(json.dumps(meta.to_dict(), indent=2))


# ────────────────────────── extraction ──────────────────────────


@dataclass
class NineSlice:
    """In-memory 9-slice (no center sprite — center is transparent)."""
    corner_tl: Image.Image
    corner_tr: Image.Image
    corner_bl: Image.Image
    corner_br: Image.Image
    edge_top: Image.Image     # full strip between top corners (height = ring_px)
    edge_bottom: Image.Image
    edge_left: Image.Image
    edge_right: Image.Image
    ring_px: int

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

    @classmethod
    def load(cls, src: Path, ring_px: int) -> "NineSlice":
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
    """
    src = source.convert("RGBA")
    w, h = src.size
    if ring_px <= 0 or ring_px * 2 >= min(w, h):
        raise ValueError(
            f"ring_px={ring_px} is invalid for source size {w}×{h} "
            f"(must be > 0 and < min(W,H)/2)"
        )
    rp = ring_px
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
    )


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
    tw, th = target_size
    mask = Image.new("L", (tw, th), 0)
    if tw - 2 * ring_px <= 0 or th - 2 * ring_px <= 0:
        return mask  # frame fills entire target — nothing to inpaint
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.rectangle(
        (ring_px, ring_px, tw - ring_px - 1, th - ring_px - 1),
        fill=255,
    )
    return mask


def interior_mask_bytes(target_size: tuple[int, int], ring_px: int) -> bytes:
    """PNG bytes for interior_mask(). Convenience for provider.inpaint()."""
    m = interior_mask(target_size, ring_px)
    buf = io.BytesIO()
    m.save(buf, format="PNG")
    return buf.getvalue()


# ────────────────────────── on-disk house frame helpers ──────────────────────────


def adopt_house_frame(slice_: NineSlice, meta: FrameMeta) -> None:
    """Replace the active house frame with this 9-slice + metadata."""
    house_dir().mkdir(parents=True, exist_ok=True)
    slice_.save(house_dir())
    write_house_meta(meta)


def load_house_frame() -> tuple[NineSlice, FrameMeta] | None:
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

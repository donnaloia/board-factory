"""The atomic generate operation: draw one cell of the board.

`draw_cell` is the only way art enters the pipeline. It works the same
for every category (spaces, panels, centerpiece) and for every modality
(txt2img, img2img, inpaint) because the difference is data on the
`DrawSpec`, not control flow.

Pipeline shape per call:

    1. Provider call (generate / img2img / inpaint per spec.mode), N candidates
    2. Inline cleanup (palette quantize + grid-snap) on each raw PNG
    3. Push every cleaned candidate into history/<category>/<asset_id>/
       with a sidecar recording the prompt actually used + provider name
    4. Promote the first candidate as live so the board updates immediately
    5. Per-candidate progress events to the sink

There is no batch generate function below this. "Generate all spaces" is
implemented in `orchestrate.py` as a loop of `draw_cell` calls.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from .. import assets, config, frames
from ..geometry import crop_region, detect_native_scale, grid_snap
from ..palette import load_palette, quantize_to_palette
from ..providers import PixelArtProvider
from ..providers.pixel.pixellab import png_bytes
from ..schemas import Catalog
from .progress import ProgressSink


# ────────────────────────── data model ──────────────────────────


DrawMode = Literal["txt2img", "img2img", "inpaint"]


@dataclass
class DrawSpec:
    """Everything `draw_cell` needs to make one cell's worth of art.

    The spec is built once by `spec_for_*` (which knows about catalog
    structure, the frame system, and style assets) and then handed to
    `draw_cell` which does mechanical work. This split keeps `draw_cell`
    free of catalog awareness and makes it trivial to dry-run.
    """

    category: Literal["spaces", "panels", "centerpiece"]
    asset_id: str
    prompt: str                       # already includes the style prefix
    base_prompt: str                  # what gets stored on the history sidecar
    size: tuple[int, int]
    candidates: int
    mode: DrawMode
    palette: list[tuple[int, int, int]] | None
    style_reference: bytes | None     # for txt2img guidance
    reference_bytes: bytes | None     # for img2img / inpaint source image
    mask_bytes: bytes | None          # for inpaint
    img2img_strength: float = 0.8


@dataclass
class DrawResult:
    spec: DrawSpec
    history_filenames: list[str]      # newest-first
    promoted_filename: str | None     # basename now live (None on failure)
    spent_usd: float


# ────────────────────────── style asset loading ──────────────────────────


def _read_style_assets() -> tuple[bytes | None, list[tuple[int, int, int]] | None]:
    """Load the style sheet PNG + palette from the active board's workspace.

    Both are written by the style step; either can be None if style hasn't
    been run yet (in which case the provider gets called without style
    guidance, which is degraded but valid).
    """
    palette = None
    pal_path = config.STYLE_DIR / "palette.json"
    if pal_path.exists():
        palette = load_palette(pal_path)
    style_ref = None
    sheet_path = config.STYLE_DIR / "style_sheet.png"
    if sheet_path.exists():
        style_ref = sheet_path.read_bytes()
    return style_ref, palette


# ────────────────────────── spec builders ──────────────────────────


def spec_for_space(
    catalog: Catalog,
    design_id: str,
    *,
    prompt_override: str | None = None,
) -> DrawSpec:
    """Build a DrawSpec for one perimeter space design.

    Spaces are pure txt2img — there is no per-position mockup region to
    condition on (one design fills many positions on the board).
    """
    design = next(
        (d for d in catalog.all_space_designs() if d.id == design_id),
        None,
    )
    if design is None:
        raise ValueError(f"Unknown space design: {design_id!r}")
    size = catalog.board_spaces.design_size(design)
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    base = prompt_override if prompt_override else design.prompt
    style_ref, palette = _read_style_assets()
    return DrawSpec(
        category="spaces",
        asset_id=design.id,
        prompt=style_prefix + base,
        base_prompt=base,
        size=size,
        candidates=config.SPACE_CANDIDATES,
        mode="txt2img",
        palette=palette,
        style_reference=style_ref,
        reference_bytes=None,
        mask_bytes=None,
    )


def spec_for_panel(
    catalog: Catalog,
    panel_id: str,
    *,
    prompt_override: str | None = None,
) -> DrawSpec:
    """Build a DrawSpec for one functional panel.

    Mode selection — this is the inpaint-vs-img2img branch that previously
    lived in `regen_one._should_inpaint_panel` + `_inpaint_panel_interior`.
    Now it's data on the spec:

      - frame system on AND a live panel asset exists  → inpaint interior
        (preserves the frame ring pixel-identical, regenerates only the
        center the user actually wants to change)
      - otherwise → img2img against the mockup bbox crop
    """
    panel = next((p for p in catalog.all_panels() if p.id == panel_id), None)
    if panel is None:
        raise ValueError(f"Unknown panel: {panel_id!r}")

    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    base = prompt_override if prompt_override else panel.prompt
    _, palette = _read_style_assets()
    target_size = panel.target_size

    use_inpaint = (
        catalog.frame.enabled
        and catalog.frame.apply_to_panels
        and frames.has_house_frame()
        and assets.live_path("panels", panel.id).exists()
    )

    if use_inpaint:
        live_path = assets.live_path("panels", panel.id)
        loaded = frames.load_house_frame()
        if loaded is None:
            # Defensive — has_house_frame just returned True.
            raise RuntimeError("Frame inpaint requested but no house frame is on disk")
        _, meta = loaded
        # ring_px is in source-asset pixels — scale to this panel's target size.
        src_w, src_h = meta.source_size
        tw, th = target_size
        scale = min(tw / src_w, th / src_h) if src_w and src_h else 1.0
        scaled_ring = max(1, int(round(meta.ring_px * scale)))
        return DrawSpec(
            category="panels",
            asset_id=panel.id,
            prompt=style_prefix + base,
            base_prompt=base,
            size=target_size,
            candidates=config.PANEL_CANDIDATES,
            mode="inpaint",
            palette=palette,
            style_reference=None,
            reference_bytes=live_path.read_bytes(),
            mask_bytes=frames.interior_mask_bytes(target_size, scaled_ring),
        )

    # img2img against the mockup region for this panel.
    mockup_path = config.BOARD_ROOT / catalog.style.reference_image
    ref_img = crop_region(
        mockup_path,
        panel.bbox,
        target_size,
        canvas_size=catalog.board_size,
    )
    return DrawSpec(
        category="panels",
        asset_id=panel.id,
        prompt=style_prefix + base,
        base_prompt=base,
        size=target_size,
        candidates=config.PANEL_CANDIDATES,
        mode="img2img",
        palette=palette,
        style_reference=None,
        reference_bytes=png_bytes(ref_img),
        mask_bytes=None,
        img2img_strength=0.8,
    )


def spec_for_centerpiece(
    catalog: Catalog,
    *,
    prompt_override: str | None = None,
) -> DrawSpec:
    """Build a DrawSpec for the centerpiece.

    **Initial generation** (no live centerpiece yet): img2img against the
    mockup bbox crop — anchors the first asset to the board sketch.

    **Regeneration** (a live centerpiece already exists): txt2img at
    ``centerpiece.target_size`` with the style sheet, same modality as
    perimeter spaces — subsequent passes are not tied to the mockup crop.
    """
    cp = catalog.centerpiece
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    base = prompt_override if prompt_override else cp.prompt
    style_ref, palette = _read_style_assets()
    target_size = cp.target_size

    if assets.has_live("centerpiece", "centerpiece"):
        return DrawSpec(
            category="centerpiece",
            asset_id="centerpiece",
            prompt=style_prefix + base,
            base_prompt=base,
            size=target_size,
            candidates=config.CENTERPIECE_CANDIDATES,
            mode="txt2img",
            palette=palette,
            style_reference=style_ref,
            reference_bytes=None,
            mask_bytes=None,
        )

    mockup_path = config.BOARD_ROOT / catalog.style.reference_image
    ref_img = crop_region(
        mockup_path,
        cp.bbox,
        target_size,
        canvas_size=catalog.board_size,
    )
    return DrawSpec(
        category="centerpiece",
        asset_id="centerpiece",
        prompt=style_prefix + base,
        base_prompt=base,
        size=target_size,
        candidates=config.CENTERPIECE_CANDIDATES,
        mode="img2img",
        palette=palette,
        style_reference=None,
        reference_bytes=png_bytes(ref_img),
        mask_bytes=None,
        img2img_strength=0.85,
    )


# ────────────────────────── cleanup (inline) ──────────────────────────


def _cleanup_one(raw_png: bytes, palette: list[tuple[int, int, int]] | None) -> bytes:
    """Pixel-discipline pass: detect upscale ratio, snap to grid, quantize to palette.

    The same code that was scattered across `regen_one._cleanup_one` and the
    standalone `cleanup` step. Inline here so a candidate is never written to
    disk in its dirty form — `history/` only ever contains cleaned PNGs.
    """
    img = Image.open(io.BytesIO(raw_png)).convert("RGBA")
    scale = detect_native_scale(img)
    snapped = grid_snap(img, scale=scale)
    if palette:
        snapped = quantize_to_palette(snapped, palette)
    out = io.BytesIO()
    snapped.save(out, format="PNG")
    return out.getvalue()


# ────────────────────────── the operation ──────────────────────────


def draw_cell(
    spec: DrawSpec,
    provider: PixelArtProvider,
    sink: ProgressSink,
) -> DrawResult:
    """Run one provider call for `spec`, clean each candidate, push to history,
    promote the first as live, return what was made.

    The provider call is one network round-trip that returns N PNGs at once
    — there is no per-candidate progress to report from inside the call. The
    sink starts at total=N and steps once per cleaned-and-archived candidate
    so the user sees forward motion immediately after the network returns.
    """
    sink.start(f"{spec.category}:{spec.asset_id}", total=spec.candidates)
    sink.log(
        f"draw {spec.category}/{spec.asset_id} "
        f"({spec.size[0]}x{spec.size[1]}, n={spec.candidates}, mode={spec.mode}, "
        f"provider={provider.name})"
    )

    estimated = provider.cost_estimate(spec.size, spec.candidates)

    try:
        raws = _provider_call(spec, provider)
    except Exception as e:
        sink.log(f"FAIL {spec.category}/{spec.asset_id}: {e}")
        return DrawResult(
            spec=spec, history_filenames=[], promoted_filename=None, spent_usd=0.0,
        )

    new_basenames: list[str] = []
    extras = {
        "provider": provider.name,
        "size": list(spec.size),
        "mode": spec.mode,
    }
    for raw in raws:
        cleaned = _cleanup_one(raw, spec.palette)
        out = assets.push_to_history(
            spec.category, spec.asset_id, cleaned,
            operation=assets.OP_REGEN,
            prompt=spec.base_prompt,
            extras=extras,
        )
        new_basenames.append(out.name)
        sink.step(out.name)

    promoted: str | None = None
    if new_basenames:
        promoted = new_basenames[0]
        assets.promote(spec.category, spec.asset_id, promoted)
        sink.log(f"promoted {promoted} -> live/{spec.category}/{spec.asset_id}")

    return DrawResult(
        spec=spec,
        history_filenames=new_basenames,
        promoted_filename=promoted,
        spent_usd=estimated,
    )


def _provider_call(spec: DrawSpec, provider: PixelArtProvider) -> list[bytes]:
    """Dispatch to the right provider method based on spec.mode.

    Argument-shape mismatches between modes are validated here so a bad spec
    fails fast with a clear message instead of a confusing TypeError from
    inside the provider client.
    """
    if spec.mode == "txt2img":
        return provider.generate(
            prompt=spec.prompt,
            size=spec.size,
            n=spec.candidates,
            style_reference=spec.style_reference,
            palette=spec.palette,
        )
    if spec.mode == "img2img":
        if spec.reference_bytes is None:
            raise ValueError("img2img requires reference_bytes on the spec")
        return provider.img2img(
            prompt=spec.prompt,
            source_image=spec.reference_bytes,
            size=spec.size,
            strength=spec.img2img_strength,
            n=spec.candidates,
            palette=spec.palette,
        )
    if spec.mode == "inpaint":
        if spec.reference_bytes is None or spec.mask_bytes is None:
            raise ValueError("inpaint requires both reference_bytes and mask_bytes")
        return provider.inpaint(
            prompt=spec.prompt,
            source_image=spec.reference_bytes,
            mask_image=spec.mask_bytes,
            n=spec.candidates,
            palette=spec.palette,
        )
    raise ValueError(f"Unknown DrawMode: {spec.mode!r}")

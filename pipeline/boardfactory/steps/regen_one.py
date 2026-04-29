"""Per-asset regeneration entrypoints used by the web app.

These mirror the batch `do_generate_*` functions in `generate.py` but
operate on a single design / panel / centerpiece. They:

1. Call the provider for exactly one asset's worth of candidates (still N,
   so the user gets a small batch to choose from on each click).
2. Apply pixel cleanup (palette quantize + grid snap) inline.
3. Push every cleaned candidate into the per-asset history dir.
4. Promote the *first* candidate as live so the board updates immediately;
   the user can scroll the history strip in the side panel to flip to any
   of the others.

Returns the realized cost in USD plus the list of new history filenames so
the web app can show them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .. import assets, config
from ..geometry import crop_region, detect_native_scale, grid_snap
from ..palette import load_palette, quantize_to_palette
from ..progress import RunStats, fmt_money, progress_bar, step
from ..providers import PixelArtProvider
from ..providers.pixel.pixellab import png_bytes
from ..schemas import Catalog


# ────────────────────────── shared helpers ──────────────────────────


@dataclass
class RegenResult:
    asset_id: str
    category: str
    spent: float
    new_history: list[str]    # basenames (newest-first)
    promoted: str | None      # basename now live (None on failure)


def _read_style_assets() -> tuple[bytes | None, list[tuple[int, int, int]] | None]:
    palette = None
    pal_path = config.STYLE_DIR / "palette.json"
    if pal_path.exists():
        palette = load_palette(pal_path)
    style_ref = None
    sheet_path = config.STYLE_DIR / "style_sheet.png"
    if sheet_path.exists():
        style_ref = sheet_path.read_bytes()
    return style_ref, palette


def _cleanup_one(raw_png: bytes, palette: list[tuple[int, int, int]] | None) -> bytes:
    """Apply palette quantize + grid snap to a single PNG and return the result."""
    img = Image.open(__import__("io").BytesIO(raw_png)).convert("RGBA")
    scale = detect_native_scale(img)
    snapped = grid_snap(img, scale=scale)
    if palette:
        snapped = quantize_to_palette(snapped, palette)
    out = __import__("io").BytesIO()
    snapped.save(out, format="PNG")
    return out.getvalue()


def _emit_to_history(
    category: str,
    asset_id: str,
    raws: list[bytes],
    palette,
    *,
    prompt_used: str,
    extras: dict | None = None,
) -> tuple[list[str], str | None]:
    """Cleanup each raw PNG, push to history with metadata, promote the first."""
    new_basenames: list[str] = []
    for raw in raws:
        cleaned = _cleanup_one(raw, palette)
        out = assets.push_to_history(
            category, asset_id, cleaned,
            operation=assets.OP_REGEN,
            prompt=prompt_used,
            extras=extras,
        )
        new_basenames.append(out.name)
    promoted: str | None = None
    if new_basenames:
        promoted = new_basenames[0]
        assets.promote(category, asset_id, promoted)
    return new_basenames, promoted


# ────────────────────────── one-asset regen: spaces ──────────────────────────


def do_regen_space(
    run: RunStats,
    catalog: Catalog,
    design_id: str,
    provider: PixelArtProvider,
    n: int | None = None,
    prompt_override: str | None = None,
) -> RegenResult:
    """Regenerate exactly one space design.

    prompt_override: if provided, used in place of the catalog prompt for this
    generation. The prompt actually used is recorded in each history entry's
    sidecar so the side panel can show 'this is the prompt that made this art'.
    """
    n = n or config.SPACE_CANDIDATES
    style_ref, palette = _read_style_assets()
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""

    design = next((d for d in catalog.all_space_designs() if d.id == design_id), None)
    if design is None:
        raise ValueError(f"Unknown space design: {design_id}")
    size = catalog.board_spaces.design_size(design)

    base_prompt = prompt_override if prompt_override else design.prompt
    full_prompt = style_prefix + base_prompt

    estimated = provider.cost_estimate(size, n)
    spent = 0.0
    new_history: list[str] = []
    promoted: str | None = None

    with step(run, f"regen-space:{design_id}") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        s.extras["size"] = f"{size[0]}×{size[1]}"
        if prompt_override:
            s.extras["prompt"] = "override"
        with progress_bar(f"{design_id} ({n} candidates)", total=n) as bar:
            try:
                raws = provider.generate(
                    prompt=full_prompt,
                    size=size,
                    n=n,
                    style_reference=style_ref,
                    palette=palette,
                )
                new_history, promoted = _emit_to_history(
                    "spaces", design_id, raws, palette,
                    prompt_used=base_prompt,
                    extras={"provider": provider.name, "size": list(size)},
                )
                spent = estimated
                s.items = len(new_history)
                bar.advance(n)
            except Exception as e:
                s.failures.append(f"{design_id}: {e}")
                bar.write(f"[red]✗[/red] {design_id}: {e}")
        s.extras["spent"] = fmt_money(spent)
        s.extras["new"] = str(len(new_history))

    return RegenResult(
        asset_id=design_id, category="spaces",
        spent=spent, new_history=new_history, promoted=promoted,
    )


# ────────────────────────── one-asset regen: panels ──────────────────────────


def do_regen_panel(
    run: RunStats,
    catalog: Catalog,
    panel_id: str,
    provider: PixelArtProvider,
    n: int | None = None,
    prompt_override: str | None = None,
) -> RegenResult:
    """Regenerate exactly one functional UI panel."""
    n = n or config.PANEL_CANDIDATES
    _, palette = _read_style_assets()
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""

    panel = next((p for p in catalog.all_panels() if p.id == panel_id), None)
    if panel is None:
        raise ValueError(f"Unknown panel: {panel_id}")

    base_prompt = prompt_override if prompt_override else panel.prompt
    full_prompt = style_prefix + base_prompt

    estimated = provider.cost_estimate(panel.target_size, n)
    spent = 0.0
    new_history: list[str] = []
    promoted: str | None = None
    mockup_path = config.BOARD_ROOT / catalog.style.reference_image

    # Decide whether to inpaint the interior only (frame system active) or
    # do a full img2img regeneration (frame off / no frame adopted / no live).
    use_inpaint = _should_inpaint_panel(catalog)
    live = assets.live_path("panels", panel_id)
    if use_inpaint and not live.exists():
        # Frame is enabled but there's nothing to inpaint into yet — fall back
        # to full img2img for the very first generation of this panel.
        use_inpaint = False

    with step(run, f"regen-panel:{panel_id}") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        s.extras["mode"] = "inpaint" if use_inpaint else "img2img"
        with progress_bar(f"{panel_id} ({n} candidates)", total=n) as bar:
            try:
                if use_inpaint:
                    raws = _inpaint_panel_interior(
                        provider=provider,
                        prompt=full_prompt,
                        live_path=live,
                        target_size=panel.target_size,
                        n=n,
                        palette=palette,
                    )
                else:
                    ref_img = crop_region(
                        mockup_path,
                        panel.bbox,
                        panel.target_size,
                        canvas_size=catalog.board_size,
                    )
                    ref_bytes = png_bytes(ref_img)
                    raws = provider.img2img(
                        prompt=full_prompt,
                        source_image=ref_bytes,
                        size=panel.target_size,
                        strength=0.8,
                        n=n,
                        palette=palette,
                    )
                new_history, promoted = _emit_to_history(
                    "panels", panel_id, raws, palette,
                    prompt_used=base_prompt,
                    extras={
                        "provider": provider.name,
                        "size": list(panel.target_size),
                        "mode": "inpaint" if use_inpaint else "img2img",
                    },
                )
                spent = estimated
                s.items = len(new_history)
                bar.advance(n)
            except Exception as e:
                s.failures.append(f"{panel_id}: {e}")
                bar.write(f"[red]✗[/red] {panel_id}: {e}")
        s.extras["spent"] = fmt_money(spent)
        s.extras["new"] = str(len(new_history))

    return RegenResult(
        asset_id=panel_id, category="panels",
        spent=spent, new_history=new_history, promoted=promoted,
    )


def _should_inpaint_panel(catalog: Catalog) -> bool:
    """True when the house-frame system is active for panels on this board."""
    from .. import frames
    return (
        catalog.frame.enabled
        and catalog.frame.apply_to_panels
        and frames.has_house_frame()
    )


def _inpaint_panel_interior(
    *,
    provider: PixelArtProvider,
    prompt: str,
    live_path,
    target_size: tuple[int, int],
    n: int,
    palette: list[tuple[int, int, int]] | None,
) -> list[bytes]:
    """Inpaint only the interior of the live panel asset, keeping the frame ring
    pixel-identical. Mask is white inside the ring, black on the ring."""
    from .. import frames
    loaded = frames.load_house_frame()
    if loaded is None:
        # Should be impossible given _should_inpaint_panel, but guard anyway.
        raise RuntimeError("Frame inpaint requested but no house frame is adopted")
    _, meta = loaded
    # ring_px is in source-asset pixels — the live panel may be a different
    # size, so scale ring_px proportionally to the panel's target size.
    src_w, src_h = meta.source_size
    tw, th = target_size
    scale = min(tw / src_w, th / src_h) if src_w and src_h else 1.0
    scaled_ring = max(1, int(round(meta.ring_px * scale)))
    mask_bytes = frames.interior_mask_bytes(target_size, scaled_ring)
    src_bytes = live_path.read_bytes()
    return provider.inpaint(
        prompt=prompt,
        source_image=src_bytes,
        mask_image=mask_bytes,
        n=n,
        palette=palette,
    )


# ────────────────────────── one-asset regen: centerpiece ──────────────────────────


def do_clean_one(
    run: RunStats,
    category: str,
    asset_id: str,
) -> RegenResult:
    """Re-run pixel cleanup (palette quantize + grid snap) on the current live
    image for one cell. Pushes the cleaned result to history with operation=clean
    and promotes it as the new live.

    Free, fast, no provider call. Useful when:
    - The palette changed after the asset was generated
    - The asset is one quantize pass away from looking right
    - You want to "tidy up" without changing the underlying composition
    """
    _, palette = _read_style_assets()
    if not palette:
        raise RuntimeError(
            "No palette found. Run the style step first so cleanup has a target palette."
        )

    live = assets.live_path(category, asset_id)
    if not live.exists():
        raise RuntimeError(
            f"No live image to clean for {category}/{asset_id}. Generate one first."
        )

    raw = live.read_bytes()
    new_history: list[str] = []
    promoted: str | None = None

    with step(run, f"clean:{category}:{asset_id}") as s:
        try:
            cleaned = _cleanup_one(raw, palette)
            out = assets.push_to_history(
                category, asset_id, cleaned,
                operation=assets.OP_CLEAN,
                prompt=None,
                extras={"palette_size": len(palette)},
            )
            new_history.append(out.name)
            assets.promote(category, asset_id, out.name)
            promoted = out.name
            s.items = 1
        except Exception as e:
            s.failures.append(f"{asset_id}: {e}")
        s.extras["palette"] = str(len(palette))
        s.extras["new"] = str(len(new_history))

    return RegenResult(
        asset_id=asset_id, category=category,
        spent=0.0, new_history=new_history, promoted=promoted,
    )


def do_regen_centerpiece(
    run: RunStats,
    catalog: Catalog,
    provider: PixelArtProvider,
    n: int | None = None,
    prompt_override: str | None = None,
) -> RegenResult:
    """Regenerate the centerpiece asset."""
    n = n or config.CENTERPIECE_CANDIDATES
    _, palette = _read_style_assets()
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    cp = catalog.centerpiece
    base_prompt = prompt_override if prompt_override else cp.prompt
    full_prompt = style_prefix + base_prompt
    estimated = provider.cost_estimate(cp.target_size, n)
    spent = 0.0
    new_history: list[str] = []
    promoted: str | None = None
    mockup_path = config.BOARD_ROOT / catalog.style.reference_image

    with step(run, "regen-centerpiece") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        with progress_bar(f"centerpiece ({n} candidates)", total=n) as bar:
            try:
                ref_img = crop_region(
                    mockup_path,
                    cp.bbox,
                    cp.target_size,
                    canvas_size=catalog.board_size,
                )
                ref_bytes = png_bytes(ref_img)
                raws = provider.img2img(
                    prompt=full_prompt,
                    source_image=ref_bytes,
                    size=cp.target_size,
                    strength=0.85,
                    n=n,
                    palette=palette,
                )
                new_history, promoted = _emit_to_history(
                    "centerpiece", "centerpiece", raws, palette,
                    prompt_used=base_prompt,
                    extras={"provider": provider.name, "size": list(cp.target_size)},
                )
                spent = estimated
                s.items = len(new_history)
                bar.advance(n)
            except Exception as e:
                s.failures.append(f"centerpiece: {e}")
                bar.write(f"[red]✗[/red] centerpiece: {e}")
        s.extras["spent"] = fmt_money(spent)
        s.extras["new"] = str(len(new_history))

    return RegenResult(
        asset_id="centerpiece", category="centerpiece",
        spent=spent, new_history=new_history, promoted=promoted,
    )

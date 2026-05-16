"""Full card assembly (§8, steps 1–10).

One call to ``generate_one_card`` produces a single composited card PNG.

**Legacy path** (opt-in via ``CARD_FACTORY_SINGLE_PASS_CARD=0`` / ``false`` / ``no`` / ``off``):

  1. Canonicalize committed frame to canvas.
  2. Resolve inner hull from committed frame metadata.
  3. Apply layout template → pixel regions.
  4. Rasterize ``M_art`` / ``M_stats``; refine ``M_art`` with frame alpha (hole).
  5. Generate illustration (frame as style ref for OpenAI, pixel + palette prompts,
     NEAREST downscale + optional palette quantize).
  6. Stats band: translucent tint sampled from frame under ``M_stats``.
  7. Procedural typography into ``M_stats_text``.
  8. Layer composite.
  9. Optional final unify (whole-card img2img, conservative) when enabled.
  10. Write live PNG + manifest.

**Single-pass path** (default): derive **organic** interior masks from the committed frame alpha
(seeded transparent connected component + erosion); inpaint into the paint mask only; art underlay
+ mat + edge strip + ``alpha_composite(underlay, frame)``. Layout ``inner_rect`` seeds hole
extraction only — not the art silhouette. Rim check, typography, chrome authority; write
``m_integrated.png`` (hole shell) and ``m_integrated_paint.png``.

Returns the path to the written PNG.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageChops

from ..config import (
    final_unify_enabled,
    frame_chrome_stamp_alpha_threshold,
    frame_hole_alpha_threshold,
    INTERIOR_CC_BBOX_PAD_PX,
    INTERIOR_CC_MIN_AREA_PX,
    INTERIOR_HOLE_ERODE_PX,
    NO_FRAME_PROMPT_PREFIX,
    SINGLE_PASS_EDGE_STRIP_PX,
    STATS_BAND_ALPHA,
    single_pass_card_enabled,
)
from ..providers.base import CardProvider
from ..schemas.manifest import CardManifest, InnerRect
from ..steps.canvas import fit_to_canvas_nearest
from ..steps.composite import (
    apply_art_mat_fill,
    apply_paint_mask_edge_strip,
    apply_committed_frame_authority,
    build_single_pass_art_layer,
    layer_composite,
    seal_single_pass_with_frame_on_top,
)
from ..steps.integration_checks import rim_matches_frame
from ..steps.integration_reference import build_single_pass_inpaint_source
from ..steps.interior_hole import build_organic_hole_masks
from ..steps.masks import build_m_art, build_m_stats, intersect_rgba_masks
from ..steps.palette_quantize import quantize_to_rgb_palette
from ..steps.stats_plate import (
    average_opaque_frame_rgb_under_mask,
    single_pass_ring_mat_rgb,
    stats_background_from_frame,
)
from ..steps.typography import draw_stat_lines


def _load_layout_template(template_path: Path | None) -> dict:
    if template_path and template_path.exists():
        return json.loads(template_path.read_text("utf-8"))
    return {
        "schema_version": "1",
        "id": "portrait-two-band-v1",
        "coordinate_space": "interior_normalized",
        "regions": [
            {"id": "main_art", "role": "illustration",
             "rect": {"x": 0, "y": 0, "width": 1, "height": 0.6667}},
            {"id": "stats", "role": "procedural_stats",
             "rect": {"x": 0, "y": 0.6667, "width": 1, "height": 0.3333},
             "typography": {
                 "padding": {"top": 0.12, "right": 0.08, "bottom": 0.1, "left": 0.08},
                 "horizontal_align": "center",
                 "vertical_align": "center",
             }},
        ],
    }


def _find_region(template: dict, role: str) -> dict | None:
    for r in template.get("regions") or []:
        if r.get("role") == role:
            return r
    return None


def _stats_text_rect(
    inner_rect: dict, stats_region: dict
) -> tuple[int, int, int, int]:
    from ..steps.masks import _hull_to_pixel_rect

    left, top, right_i, bottom_i = _hull_to_pixel_rect(inner_rect, stats_region["rect"])
    sw = right_i - left + 1
    sh = bottom_i - top + 1
    typo = stats_region.get("typography") or {}
    pad = typo.get("padding") or {}
    pt = round(sh * pad.get("top", 0.1))
    pr = round(sw * pad.get("right", 0.08))
    pb = round(sh * pad.get("bottom", 0.1))
    pl = round(sw * pad.get("left", 0.08))
    return (left + pl, top + pt, right_i + 1 - pr, bottom_i + 1 - pb)


def generate_one_card(
    *,
    deck_id: str,
    slot_index: int,
    frame_commit_id: int,
    committed_frame_png: Path,
    committed_inner_rect: dict,
    canvas: tuple[int, int],
    illustration_prompt: str,
    stat_lines: list[str],
    palette_colors: list[tuple[int, int, int]],
    provider: CardProvider,
    output_path: Path,
    masks_dir: Path,
    history_dir: Path,
    layout_template_path: Path | None = None,
    layout_template_id: str = "portrait-two-band-v1",
    sink,
) -> Path:
    """Assemble one card through steps 1–9.  Returns the path of the live PNG."""

    canvas_w, canvas_h = canvas

    hole_thr = frame_hole_alpha_threshold()
    stamp_thr = frame_chrome_stamp_alpha_threshold()

    sink.emit("canonicalize", f"slot {slot_index}", pct=5)

    # ── step 1: canonicalize frame PNG to canvas ──
    frame_img = Image.open(str(committed_frame_png)).convert("RGBA")
    if frame_img.size != canvas:
        frame_img = frame_img.resize(canvas, Image.LANCZOS)

    # ── step 2: resolve inner hull from committed frame metadata ──
    inner_rect = committed_inner_rect

    # ── step 3: apply layout template ──
    template = _load_layout_template(layout_template_path)
    layout_id = template.get("id", layout_template_id)

    ill_region = _find_region(template, "illustration")
    stats_region = _find_region(template, "procedural_stats")
    if not ill_region or not stats_region:
        raise RuntimeError(
            f"Layout template {layout_id!r} missing 'illustration' or 'procedural_stats'."
        )

    # ── step 4: organic interior masks + template bands (layout JSON for bands + seed only) ──
    sink.emit("masks", f"slot {slot_index}", pct=15)
    m_hole_outer, m_hole_paint, hole_mask_fallback = build_organic_hole_masks(
        frame_img,
        canvas,
        inner_rect,
        hole_alpha_threshold=hole_thr,
        rim_erode_px=INTERIOR_HOLE_ERODE_PX,
        cc_bbox_pad_px=INTERIOR_CC_BBOX_PAD_PX,
        min_area_px=INTERIOR_CC_MIN_AREA_PX,
    )
    if hole_mask_fallback:
        sink.emit(
            "organic_hole_fallback",
            f"slot {slot_index} — interior mask used rectangular hull fallback",
            pct=16,
        )
    m_art = intersect_rgba_masks(
        build_m_art(canvas, inner_rect, ill_region["rect"]),
        m_hole_paint,
    )
    m_stats = intersect_rgba_masks(
        build_m_stats(canvas, inner_rect, stats_region["rect"]),
        m_hole_paint,
    )

    # Save masks for reproducibility / debugging
    masks_dir.mkdir(parents=True, exist_ok=True)
    m_art.save(str(masks_dir / "m_art.png"))
    m_stats.save(str(masks_dir / "m_stats.png"))

    stats_text_rect = _stats_text_rect(inner_rect, stats_region)
    typo = stats_region.get("typography") or {}

    used_single_pass = False
    prompt_hash: str
    integrated_prompt = illustration_prompt
    full_prompt = NO_FRAME_PROMPT_PREFIX + illustration_prompt

    if single_pass_card_enabled():
        m_integrated = m_hole_outer
        m_integrated_inset = m_hole_paint
        m_integrated.save(str(masks_dir / "m_integrated.png"))
        m_integrated_inset.save(str(masks_dir / "m_integrated_paint.png"))
        sink.emit(
            "integrated_inpaint",
            f"slot {slot_index} — organic interior hole (single-pass)",
            pct=25,
        )
        source = build_single_pass_inpaint_source(frame_img, canvas, m_integrated_inset)
        painted = provider.paint_integrated_card(
            canvas=canvas,
            source_image=source,
            edit_mask=m_integrated_inset,
            prompt=integrated_prompt,
            palette_colors=palette_colors,
        )
        painted = fit_to_canvas_nearest(painted, canvas)
        if palette_colors:
            painted = quantize_to_rgb_palette(painted, palette_colors)
        art_layer = build_single_pass_art_layer(canvas, painted, m_integrated_inset)
        ring_l = ImageChops.subtract(
            m_integrated.convert("L"), m_integrated_inset.convert("L")
        )
        if ring_l.getbbox():
            mat_rgb = single_pass_ring_mat_rgb(frame_img, painted, canvas, ring_l)
            art_layer = apply_art_mat_fill(
                art_layer, frame_img, m_integrated, m_integrated_inset, mat_rgb
            )
        else:
            mat_rgb = single_pass_ring_mat_rgb(
                frame_img, painted, canvas, m_integrated.convert("L")
            )

        if SINGLE_PASS_EDGE_STRIP_PX > 0:
            art_layer = apply_paint_mask_edge_strip(
                art_layer, m_integrated_inset, mat_rgb, SINGLE_PASS_EDGE_STRIP_PX
            )

        preview = Image.alpha_composite(
            art_layer.convert("RGBA"), frame_img.convert("RGBA")
        )
        if rim_matches_frame(preview, frame_img):
            sink.emit("typography", f"slot {slot_index}", pct=70)
            typo_layer = draw_stat_lines(
                canvas,
                stat_lines,
                stats_text_rect=stats_text_rect,
                h_align=typo.get("horizontal_align", "center"),
                v_align=typo.get("vertical_align", "center"),
            )
            sink.emit(
                "composite",
                f"slot {slot_index} (art underlay + typography + frame overlay)",
                pct=80,
            )
            card = seal_single_pass_with_frame_on_top(
                art_layer,
                frame_img,
                typo_layer,
                chrome_alpha_threshold=stamp_thr,
            )
            prompt_hash = hashlib.sha256(integrated_prompt.encode()).hexdigest()[
                :16
            ]
            used_single_pass = True
        else:
            sink.emit(
                "single_pass_fallback",
                f"slot {slot_index}: rim check failed — legacy path",
                pct=28,
            )

    if not used_single_pass:
        # ── step 5: generate illustration (masked) ──
        sink.emit("illustration", f"slot {slot_index} — calling provider", pct=25)
        illustration = provider.generate_illustration(
            canvas=canvas,
            m_art=m_art,
            prompt=full_prompt,
            palette_colors=palette_colors,
            style_reference=frame_img,
        )
        illustration = fit_to_canvas_nearest(illustration, canvas)
        if palette_colors:
            illustration = quantize_to_rgb_palette(illustration, palette_colors)

        transparent = Image.new("RGBA", canvas, (0, 0, 0, 0))
        illustration = Image.composite(
            illustration, transparent, m_art.convert("L")
        )

        # ── step 6: stat band background prep ──
        sink.emit("stats_band", f"slot {slot_index}", pct=60)
        stats_bg = stats_background_from_frame(
            frame_img, canvas, m_stats, alpha=STATS_BAND_ALPHA
        )

        # ── step 7: procedural typography ──
        sink.emit("typography", f"slot {slot_index}", pct=70)
        typo_layer = draw_stat_lines(
            canvas,
            stat_lines,
            stats_text_rect=stats_text_rect,
            h_align=typo.get("horizontal_align", "center"),
            v_align=typo.get("vertical_align", "center"),
        )

        # ── step 8: layer composite ──
        sink.emit("composite", f"slot {slot_index}", pct=80)
        card = layer_composite(
            canvas=canvas,
            illustration=illustration,
            m_art=m_art,
            stats_background=stats_bg,
            m_stats=m_stats,
            frame_png=frame_img,
            typography_layer=typo_layer,
            chrome_alpha_threshold=stamp_thr,
        )
        prompt_hash = hashlib.sha256(full_prompt.encode()).hexdigest()[:16]

    if not used_single_pass and final_unify_enabled():
        sink.emit(
            "unify",
            f"slot {slot_index} — whole-card cohesion (conservative)",
            pct=83,
        )
        try:
            card = provider.unify_finished_card(
                card=card,
                canvas=canvas,
                palette_colors=palette_colors,
            )
            if palette_colors:
                card = quantize_to_rgb_palette(card, palette_colors)
            card = apply_committed_frame_authority(
                card,
                frame_img,
                chrome_alpha_threshold=stamp_thr,
            )
        except Exception as exc:
            sink.emit(
                "unify_skipped",
                f"slot {slot_index}: {type(exc).__name__}: {exc}",
                pct=83,
            )

    # ── step 9: write live PNG + manifest ──
    sink.emit("publish", f"slot {slot_index}", pct=90)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(str(output_path), format="PNG")

    # Archive to history
    history_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    (history_dir / f"{ts}_card.png").write_bytes(output_path.read_bytes())

    manifest = CardManifest(
        deck_id=deck_id,
        slot_index=slot_index,
        frame_commit_id=frame_commit_id,
        layout_template_id=layout_id,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        inner_rect=InnerRect(**inner_rect),
        illustration_prompt_hash=prompt_hash,
        provider=str(provider.__class__.__name__),
        model_id=provider.model_id(),
        created_ms=ts,
    )
    (output_path.parent / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    sink.emit("publish", f"slot {slot_index} complete", pct=100)
    return output_path

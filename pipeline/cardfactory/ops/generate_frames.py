"""Frame gate — generate chrome candidates (§8.2 / §7).

Runs ``FRAME_CANDIDATE_COUNT`` (default 3) provider calls, each producing
one chrome candidate PNG:

1. Compute inner hull from canvas + default margin.
2. Load layout template → derive illustration aperture + stats glyph box.
3. Build ``M_chrome_paint`` (allowed paint region).
4. For each candidate: call provider, post-decode clamp forbidden zones, save.
5. Write ``FrameCandidateManifest`` per candidate.

Returns a list of candidate dicts (one per candidate) consumed by the job
adapter to write ``card_frame_candidates`` rows.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from PIL import Image

from ..config import (
    DEFAULT_FRAME_MARGIN,
    FRAME_CANDIDATE_COUNT,
    ILLUSTRATION_INNER_MAT_PX,
    INTERIOR_CC_BBOX_PAD_PX,
    INTERIOR_CC_MIN_AREA_PX,
    INTERIOR_HOLE_ERODE_PX,
    frame_hole_alpha_threshold,
)
from ..providers.base import CardProvider
from ..schemas.manifest import FrameCandidateManifest, InnerRect
from ..steps.canvas import compute_inner_rect
from ..steps.interior_hole import harden_chrome_frame_png
from ..steps.masks import (
    build_m_chrome_paint,
    clamp_forbidden_zones,
    mask_hash,
)


def _load_layout_template(template_path: Path | None) -> dict:
    """Load layout template JSON.  Falls back to the default two-band layout."""
    if template_path and template_path.exists():
        return json.loads(template_path.read_text("utf-8"))
    # Inline minimal fallback (portrait-two-band-v1)
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
                 "padding": {"top": 0.12, "right": 0.08, "bottom": 0.1, "left": 0.08}
             }},
        ],
    }


def _find_region(template: dict, role: str) -> dict | None:
    for r in template.get("regions") or []:
        if r.get("role") == role:
            return r
    return None


def _get_typography_padding(region: dict) -> dict:
    typo = region.get("typography") or {}
    return typo.get("padding") or {"top": 0.1, "right": 0.08, "bottom": 0.1, "left": 0.08}


def _illustration_pixel_rect(inner_rect: dict, ill_region: dict) -> tuple[int, int, int, int]:
    from ..steps.masks import _hull_to_pixel_rect
    return _hull_to_pixel_rect(inner_rect, ill_region["rect"])


def _stats_text_pixel_rect(
    inner_rect: dict, stats_region: dict
) -> tuple[int, int, int, int]:
    from ..steps.masks import _hull_to_pixel_rect

    left, top, right_i, bottom_i = _hull_to_pixel_rect(inner_rect, stats_region["rect"])
    sw = right_i - left + 1
    sh = bottom_i - top + 1
    pad = _get_typography_padding(stats_region)
    pt = round(sh * pad.get("top", 0))
    pr = round(sw * pad.get("right", 0))
    pb = round(sh * pad.get("bottom", 0))
    pl = round(sw * pad.get("left", 0))
    # Inclusive box for :meth:`ImageDraw.rectangle` (Pillow ≥ 11.3).
    return (left + pl, top + pt, right_i - pr, bottom_i - pb)


def generate_frames(
    *,
    deck_id: str,
    job_id: str,
    canvas: tuple[int, int],
    style_prompt: str,
    palette_colors: list[tuple[int, int, int]],
    provider: CardProvider,
    output_dir: Path,
    layout_template_path: Path | None = None,
    sink,
) -> list[dict]:
    """Generate chrome candidates and write PNGs + manifests.

    Returns a list of candidate descriptor dicts ready for DB insertion:
    ``[{candidate_index, rel_path, inner_rect, m_chrome_paint_hash, provider, model_id}, ...]``
    """
    canvas_w, canvas_h = canvas
    template = _load_layout_template(layout_template_path)
    layout_id = template.get("id", "portrait-two-band-v1")

    inner_rect = compute_inner_rect(canvas_w, canvas_h, margin=DEFAULT_FRAME_MARGIN)

    ill_region = _find_region(template, "illustration")
    stats_region = _find_region(template, "procedural_stats")

    if not ill_region or not stats_region:
        raise RuntimeError(
            f"Layout template {layout_id!r} must define both 'illustration' and "
            "'procedural_stats' regions."
        )

    ill_pixel_rect = _illustration_pixel_rect(inner_rect, ill_region)
    stats_text_pixel_rect = _stats_text_pixel_rect(inner_rect, stats_region)

    sink.emit("build_mask", "computing M_chrome_paint", pct=5)
    m_chrome_paint = build_m_chrome_paint(
        canvas=(canvas_w, canvas_h),
        inner_rect=inner_rect,
        illustration_region=ill_region["rect"],
        stats_region=stats_region["rect"],
        typography_padding=_get_typography_padding(stats_region),
        illustration_inner_mat_px=ILLUSTRATION_INNER_MAT_PX,
    )
    paint_hash = mask_hash(m_chrome_paint)

    chrome_prompt = (
        f"A decorative pixel-art collectible card frame with ornate border and stats plaque. "
        f"Style: {style_prompt or 'fantasy pixel art'}. "
        "Leave the illustration window and stats glyph plate completely empty — transparent holes only. "
        "Ornament belongs in the chrome ring and plaque surround, not inside those cutouts."
    )

    candidates: list[dict] = []
    now_ms = int(time.time() * 1000)

    for idx in range(FRAME_CANDIDATE_COUNT):
        sink.emit(
            "chrome_gen",
            f"candidate {idx + 1}/{FRAME_CANDIDATE_COUNT}",
            pct=10 + (idx * 80 // FRAME_CANDIDATE_COUNT),
        )

        raw = provider.generate_chrome_candidate(
            canvas=canvas,
            m_chrome_paint=m_chrome_paint,
            prompt=chrome_prompt,
            palette_colors=palette_colors,
        )

        # ── post-decode hardening (§8.2): force transparency in forbidden zones ──
        hardened = clamp_forbidden_zones(
            raw,
            illustration_region_rect=ill_pixel_rect,
            stats_text_rect=stats_text_pixel_rect,
            illustration_inner_mat_px=ILLUSTRATION_INNER_MAT_PX,
        )

        # Ensure canvas size
        if hardened.size != canvas:
            hardened = hardened.resize(canvas, Image.LANCZOS)

        hole_thr = frame_hole_alpha_threshold()
        hardened = harden_chrome_frame_png(
            hardened,
            canvas,
            inner_rect,
            stats_text_pixel_rect,
            hole_alpha_threshold=hole_thr,
            rim_erode_px=INTERIOR_HOLE_ERODE_PX,
            cc_bbox_pad_px=INTERIOR_CC_BBOX_PAD_PX,
            min_area_px=INTERIOR_CC_MIN_AREA_PX,
        )

        # Write PNG
        output_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_dir / f"candidate_{idx}.png"
        hardened.save(str(png_path), format="PNG")

        # Write manifest
        manifest = FrameCandidateManifest(
            deck_id=deck_id,
            job_id=job_id,
            candidate_index=idx,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            inner_rect=InnerRect(**inner_rect),
            m_chrome_paint_hash=paint_hash,
            provider=str(provider.__class__.__name__),
            model_id=provider.model_id(),
            layout_template_id=layout_id,
            created_ms=now_ms,
        )
        (output_dir / f"candidate_{idx}_manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )

        candidates.append(
            {
                "candidate_index": idx,
                "rel_path": f"frames/candidates/job_{job_id}/candidate_{idx}.png",
                "inner_rect": inner_rect,
                "m_chrome_paint_hash": paint_hash,
                "provider": str(provider.__class__.__name__),
                "model_id": provider.model_id(),
            }
        )

    sink.emit("chrome_gen", "all candidates written", pct=100)
    return candidates

"""Board JSON/binary routes — pipeline actions, generation API, frame tooling."""

from __future__ import annotations

import base64
import io
import json as _json_std
import os
import shutil
import tempfile
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from PIL import Image, ImageChops
from pydantic import BaseModel, field_validator

from auth.middleware import current_user, require_user
from domains.boards import pipeline_jobs
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from boardfactory import frames_inference as bf_frames_inference
from boardfactory.providers.pixel.pixellab import list_pixellab_presets
from boardfactory.schemas import Catalog

from domains.boards.routes_common import NestedBoardId, board_prefix
from infrastructure import deps
from domains.boards import services as svc_boards
from domains.spaces import services as svc_spaces
from domains.spaces.assets import services as asset_urls
from domains.boards import mockup_prompt as mockup_prompt_svc
from domains.boards.exporter import run_board_export
from domains.boards.exporter.state import BoardExportOptions
from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws

router = APIRouter()


@router.get("/users/{username}/board-games/{path_slug}/frame.png")
def frame_overlay(request: Request, board_id: NestedBoardId, w: int = 0, h: int = 0):
    """Compose the house frame at the requested size on demand. Cacheable."""
    with bf_config.set_active_board(board_id):
        loaded = bf_frames.load_house_frame()
    if loaded is None:
        raise HTTPException(404, "No house frame adopted on this board")

    slice_, _meta = loaded
    if w <= 0 or h <= 0:
        target = (slice_.corner_tl.width + slice_.corner_tr.width + slice_.edge_top.width,
                  slice_.corner_tl.height + slice_.corner_bl.height + slice_.edge_left.height)
    else:
        target = (w, h)
    img = bf_frames.compose_frame(slice_, target)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _try_load_proposal_masks(
    board_id: str,
    job_id: str,
    candidate_index: int,
    source_kind: str,
    source_id: str,
) -> tuple[Image.Image, Image.Image] | None:
    """Return ``(hole_mask, rim_mask)`` at full source resolution, or ``None``."""
    manifest_p = (
        fs_ws.board_root(board_id)
        / "workspace"
        / "frames"
        / "_proposals"
        / job_id
        / "manifest.json"
    )
    if not manifest_p.exists():
        return None
    try:
        man = _json_std.loads(manifest_p.read_text())
    except (OSError, ValueError, TypeError):
        return None
    if man.get("source_id") != source_id:
        return None
    if not bf_frames.frame_source_kinds_match(man.get("source_kind"), source_kind):
        return None
    cands = man.get("candidates") or []
    if not (0 <= candidate_index < len(cands)):
        return None
    cand = cands[candidate_index]
    hole_f = cand.get("hole_mask_filename")
    rim_f = cand.get("rim_mask_filename")
    if not hole_f or not rim_f:
        return None
    d = fs_ws.board_root(board_id) / "workspace" / "frames" / "_proposals" / job_id
    hp, rp = d / str(hole_f), d / str(rim_f)
    if not hp.exists() or not rp.exists():
        return None
    return Image.open(hp).convert("L"), Image.open(rp).convert("L")


def _compose_masked_frame_preview(
    src_rgba: Image.Image,
    hole_m: Image.Image,
    rim_m: Image.Image,
    interior: Image.Image,
) -> Image.Image:
    """Same-size preview: alternate interior under ``hole_m``, source rim under ``rim_m``."""
    w, h = src_rgba.size
    int_layer = (
        interior.resize((w, h), Image.NEAREST)
        if interior.size != (w, h) else interior.convert("RGBA")
    )
    r, g, b, a = int_layer.split()
    new_a = ImageChops.multiply(a, hole_m)
    int_layer = Image.merge("RGBA", (r, g, b, new_a))
    rim_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rim_layer.paste(src_rgba, (0, 0), rim_m)
    return Image.alpha_composite(int_layer, rim_layer)


@router.get("/users/{username}/board-games/{path_slug}/api/frame/preview.png")
def api_frame_preview(
    request: Request, board_id: NestedBoardId, source_kind: str, source_id: str,
    ring_px: int, w: int = 260, h: int = 240,
    job_id: str | None = None,
    candidate_index: int | None = None,
    x1: int | None = None,
    y1: int | None = None,
    x2: int | None = None,
    y2: int | None = None,
):
    """Live preview at typical panel size.

    When a vision proposal is available (``job_id`` + ``candidate_index`` + masks on
    disk), the preview composites **actual rim/hole masks** from AI — irregular
    contours, not only a rectangular nine-slice. Otherwise it falls back to the
    geometric nine-slice path (upload-only / no proposal).

    Crop order for the source tile matches refine (query bbox, else manifest).

    **Hole interior:** Another live UI space cover-cropped to the thumbnail when
    possible; else the rim source fills the hole region.

    **mask_diagnostic=1:** Return rim/hole tint overlay only (same palette as
    proposal cards) so preserve vs regenerate regions are obvious before commit.
    """
    mask_diagnostic = (
        request.query_params.get("mask_diagnostic", "").lower() in ("1", "true", "yes")
    )

    if ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    catalog = deps.load_board_catalog(board_id)
    src_img, src_size = _load_atelier_source(board_id, catalog, source_kind, source_id)
    full_src = src_img
    fw, fh = full_src.size
    crop_rect = (0, 0, fw, fh)

    def _crop_src_to_bbox(img: Image.Image, bx1: int, by1: int, bx2: int, by2: int) -> Image.Image:
        W, H = img.size
        bx1 = max(0, min(W, bx1))
        by1 = max(0, min(H, by1))
        bx2 = max(0, min(W, bx2))
        by2 = max(0, min(H, by2))
        if bx2 <= bx1 or by2 <= by1:
            return img
        return img.crop((bx1, by1, bx2, by2))

    if None not in (x1, y1, x2, y2):
        bx1, by1, bx2, by2 = int(x1), int(y1), int(x2), int(y2)
        crop_rect = (
            max(0, min(fw, bx1)),
            max(0, min(fh, by1)),
            max(0, min(fw, bx2)),
            max(0, min(fh, by2)),
        )
        src_img = _crop_src_to_bbox(full_src, *crop_rect)
    elif job_id is not None and candidate_index is not None:
        manifest_p = (
            fs_ws.board_root(board_id)
            / "workspace"
            / "frames"
            / "_proposals"
            / job_id
            / "manifest.json"
        )
        if manifest_p.exists():
            try:
                man = _json_std.loads(manifest_p.read_text())
                if (
                    bf_frames.frame_source_kinds_match(man.get("source_kind"), source_kind)
                    and man.get("source_id") == source_id
                ):
                    cands = man.get("candidates") or []
                    if 0 <= candidate_index < len(cands):
                        bb = cands[candidate_index].get("bbox")
                        if isinstance(bb, (list, tuple)) and len(bb) == 4:
                            bx1, by1, bx2, by2 = (
                                int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])
                            )
                            crop_rect = (
                                max(0, min(fw, bx1)),
                                max(0, min(fh, by1)),
                                max(0, min(fw, bx2)),
                                max(0, min(fh, by2)),
                            )
                            src_img = _crop_src_to_bbox(full_src, *crop_rect)
            except (OSError, ValueError, TypeError, KeyError, IndexError):
                pass

    mask_hole: Image.Image | None = None
    mask_rim: Image.Image | None = None
    if job_id is not None and candidate_index is not None:
        mpair = _try_load_proposal_masks(
            board_id, job_id, candidate_index, source_kind, source_id,
        )
        if mpair is not None:
            mh, mr = mpair
            if mh.size == (fw, fh) == mr.size:
                cx1, cy1, cx2, cy2 = crop_rect
                mask_hole = mh.crop((cx1, cy1, cx2, cy2))
                mask_rim = mr.crop((cx1, cy1, cx2, cy2))

    sw, sh = src_img.size
    use_masks = (
        mask_hole is not None
        and mask_rim is not None
        and mask_hole.size == (sw, sh)
        and mask_rim.size == (sw, sh)
    )

    if use_masks:
        src_rs = (
            src_img.resize((w, h), Image.NEAREST)
            if (sw, sh) != (w, h) else src_img
        )
        hole_rs = mask_hole.resize((w, h), Image.NEAREST)
        rim_rs = mask_rim.resize((w, h), Image.NEAREST)
        interior = src_rs
        alt_sid = _pick_alternate_live_space_id(board_id, catalog, source_id)
        if alt_sid:
            alt_path = fs_ws.live_path(board_id, "spaces", alt_sid)
            try:
                if alt_path.exists():
                    interior = _cover_resize_nearest(
                        Image.open(alt_path).convert("RGBA"),
                        w,
                        h,
                    )
            except (OSError, ValueError):
                pass
        if mask_diagnostic:
            out = bf_frames_inference.overlay_for_review(src_rs, rim_rs, hole_rs)
        else:
            out = _compose_masked_frame_preview(src_rs, hole_rs, rim_rs, interior)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return StreamingResponse(
            io.BytesIO(buf.getvalue()),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    eff_ring = ring_px
    if (sw, sh) != (w, h):
        scale = min(w / sw, h / sh)
        eff_ring = max(2, min(int(round(ring_px * scale)), min(w, h) // 2 - 1))
        if eff_ring * 2 >= min(w, h):
            raise HTTPException(
                400,
                f"ring_px={ring_px} too thick when scaled to preview {w}×{h}",
            )
        src_img = src_img.resize((w, h), Image.NEAREST)
        sw, sh = w, h
    elif eff_ring * 2 >= min(sw, sh):
        raise HTTPException(400, f"ring_px={ring_px} too thick for source {src_size}")

    slice_ = bf_frames.extract_9slice(src_img, eff_ring)
    rp = slice_.ring_px
    composed = bf_frames.compose_frame(slice_, (w, h))

    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hole_w = w - 2 * rp
    hole_h = h - 2 * rp
    if hole_w > 0 and hole_h > 0 and sw - 2 * rp > 0 and sh - 2 * rp > 0:
        inner: Image.Image | None = None
        alt_sid = _pick_alternate_live_space_id(board_id, catalog, source_id)
        if alt_sid:
            alt_path = fs_ws.live_path(board_id, "spaces", alt_sid)
            try:
                if alt_path.exists():
                    inner = _cover_resize_nearest(
                        Image.open(alt_path).convert("RGBA"),
                        hole_w,
                        hole_h,
                    )
            except (OSError, ValueError):
                inner = None
        if inner is None:
            inner = src_img.crop((rp, rp, sw - rp, sh - rp))
            if inner.size != (hole_w, hole_h):
                inner = inner.resize((hole_w, hole_h), Image.NEAREST)
        base.paste(inner, (rp, rp))

    out = Image.alpha_composite(base, composed)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return StreamingResponse(
        io.BytesIO(buf.getvalue()),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/users/{username}/board-games/{path_slug}/api/generation")
def api_get_generation(request: Request, board_id: NestedBoardId):
    """JSON for the generation settings modal (palette, provider, models)."""
    catalog = deps.load_board_catalog(board_id)
    settings = svc_boards.read_generation(catalog)
    return JSONResponse({
        "settings": settings,
        "options": {"pixellab_models": list_pixellab_presets()},
    })


# ═══ POST / PUT: nested (canonical) ═══


async def _action_upload_mockup(
    request: Request, board_id: str, file: UploadFile,
) -> JSONResponse:
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image (PNG or JPEG).")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file received.")

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise HTTPException(400, "Could not read image — make sure it is a valid PNG or JPEG.")

    w, h = img.size
    ratio = w / h if h else 0
    target = 16 / 9
    warn = abs(ratio - target) / target > 0.05

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    bs.get_store().write_bytes(board_id, "mockup/board.png", buf.getvalue())
    bp = board_prefix(board_id)
    return JSONResponse({
        "ok": True,
        "size": [w, h],
        "warn_aspect": warn,
        "redirect": f"{bp}/setup?mockup_ready=1",
    })


@router.post("/users/{username}/board-games/{path_slug}/actions/upload-mockup")
async def action_upload_mockup_nested(
    request: Request, board_id: NestedBoardId, file: UploadFile = File(...),
):
    return await _action_upload_mockup(request, board_id, file)


async def _action_generate_mockup(request: Request, board_id: str) -> JSONResponse:
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required.")
    if len(prompt) > 4000:
        raise HTTPException(400, "Prompt is too long (max 4000 chars).")

    user = current_user(request)
    openai_key = (user.openai_api_key if user else "") or os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(
            400,
            "No OpenAI API key found. Save one in Account → Connections → OpenAI / ChatGPT.",
        )

    catalog = deps.load_board_catalog(board_id)
    settings = svc_boards.read_generation(catalog)
    oa_model = settings["openai"]["model"]
    oa_quality = settings["openai"]["quality"]

    framing_suffix = (
        " — single unified 16:9 tabletop board illustration, even readable zones, "
        "rich cohesive palette; decorate borders only where they clarify zones."
    )
    full_prompt = mockup_prompt_svc.compose_mockup_image_prompt(
        prompt, catalog, framing_suffix=framing_suffix
    )
    if len(full_prompt) > 10000:
        raise HTTPException(
            400,
            "Combined prompt is too long after adding layout hints; shorten your description.",
        )

    api_size = "1536x1024"
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": oa_model,
                    "prompt": full_prompt,
                    "n": 1,
                    "size": api_size,
                    "quality": oa_quality,
                },
            )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI request failed: {e}")

    if r.status_code != 200:
        try:
            err_msg = r.json().get("error", {}).get("message") or r.text[:200]
        except Exception:
            err_msg = r.text[:200]
        raise HTTPException(r.status_code, f"OpenAI: {err_msg}")

    payload = r.json()
    items = payload.get("data") or []
    if not items:
        raise HTTPException(502, "OpenAI returned no image.")
    item = items[0]
    if item.get("b64_json"):
        png_bytes = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        async with httpx.AsyncClient(timeout=60.0) as client:
            ir = await client.get(item["url"])
        if ir.status_code != 200:
            raise HTTPException(502, f"Failed to download generated image (HTTP {ir.status_code}).")
        png_bytes = ir.content
    else:
        raise HTTPException(502, "OpenAI response did not include image data.")

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    src_w, src_h = img.size
    target_ratio = 16 / 9
    if src_w / src_h > target_ratio:
        new_w = int(round(src_h * target_ratio))
        x0 = (src_w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, src_h))
    elif src_w / src_h < target_ratio:
        new_h = int(round(src_w / target_ratio))
        y0 = (src_h - new_h) // 2
        img = img.crop((0, y0, src_w, y0 + new_h))
    img = img.resize((1920, 1080), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    bs.get_store().write_bytes(board_id, "mockup/board.png", buf.getvalue())
    bp = board_prefix(board_id)
    return JSONResponse({
        "ok": True,
        "size": [1920, 1080],
        "warn_aspect": False,
        "redirect": f"{bp}/setup?mockup_ready=1",
    })


@router.post("/users/{username}/board-games/{path_slug}/actions/generate-mockup")
async def action_generate_mockup_nested(request: Request, board_id: NestedBoardId):
    return await _action_generate_mockup(request, board_id)


async def _api_frame_adopt(
    request: Request, board_id: str,
    source_kind: str,
    source_id: str,
    ring_px: int,
    enable_after: bool,
) -> JSONResponse:
    """Legacy (pre-Atelier) one-shot adopt path.

    Kept around as the deterministic shortcut behind ``POST /api/frame/commit``
    when the user picks the "no vision" candidate. It also remains the
    transitional implementation behind ``POST /api/frame/adopt`` for one
    release cycle.
    """
    if ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    source_kind = bf_frames.normalize_frame_source_kind(source_kind)
    if source_kind not in bf_frames.VALID_FRAME_SOURCE_KINDS:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")

    catalog = deps.load_board_catalog(board_id)
    src_img, src_size = _load_atelier_source(board_id, catalog, source_kind, source_id)

    if ring_px * 2 >= min(src_size):
        raise HTTPException(400, f"ring_px={ring_px} is too thick for source {src_size}")

    from domains.spaces import frames_repository as frames_repo

    with bf_config.scope_board(board_id):
        slice_ = bf_frames.extract_9slice(src_img, ring_px)
        instance = bf_frames.FrameInstance(
            ring_px=ring_px,
            source_kind=source_kind,
            source_id=source_id,
            source_size=src_size,
            model_id="deterministic",
            notes="adopted via legacy /adopt path",
        )
        bf_frames.adopt_house_frame(slice_, instance)
        view = frames_repo.replace_active(board_id, instance=instance)

    if enable_after:
        svc_boards.set_frame_flags(board_id, enabled=True, apply_to_panels=True)

    return JSONResponse({
        "ok": True,
        "frame_id": view.id,
        "ring_px": ring_px,
        "source_kind": source_kind,
        "source_id": source_id,
    })


@router.post("/users/{username}/board-games/{path_slug}/api/frame/adopt")
async def api_frame_adopt_legacy(
    request: Request, board_id: NestedBoardId,
    source_kind: str = Form(...),
    source_id: str = Form(...),
    ring_px: int = Form(...),
    enable_after: bool = Form(default=True),
):
    """DEPRECATED: superseded by ``POST /api/frame/commit``.

    Returns a successful response for one release cycle so already-running
    pages keep working; new UI must call ``/commit`` (which goes through
    the Propose/Refine flow and enqueues Approach D). Slated for removal.
    """
    return await _api_frame_adopt(
        request, board_id, source_kind, source_id, ring_px, enable_after,
    )


async def _api_frame_disable(request: Request, board_id: str) -> JSONResponse:
    svc_boards.set_frame_flags(board_id, enabled=False)

    from domains.spaces import frames_repository as frames_repo

    n = frames_repo.mark_all_inactive(board_id)
    return JSONResponse({"ok": True, "deactivated_rows": n})


@router.post("/users/{username}/board-games/{path_slug}/api/frame/disable")
async def api_frame_disable_nested(request: Request, board_id: NestedBoardId):
    return await _api_frame_disable(request, board_id)


# ────────────────────────── frame atelier (Propose / Commit / Upload) ──────────────────────────


def _proposals_dir(board_id: str, job_id: str):
    return fs_ws.board_root(board_id) / "workspace" / "frames" / "_proposals" / job_id


def _proposals_static_url(board_id: str, job_id: str, filename: str) -> str:
    return (
        f"{board_prefix(board_id)}/asset/frames/_proposals/{job_id}/{filename}"
    )


def _load_atelier_source(
    board_id: str,
    catalog: dict,
    source_kind: str,
    source_id: str,
) -> tuple[Image.Image, tuple[int, int]]:
    """Load the RGBA image used by Frame Atelier propose/refine/commit."""
    sk = bf_frames.normalize_frame_source_kind(source_kind)
    if sk not in bf_frames.VALID_FRAME_SOURCE_KINDS:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")
    if sk == "functional":
        live = fs_ws.live_path(board_id, "panels", source_id)
        if not live.exists():
            raise HTTPException(404, f"No live panel asset for {source_id}")
        src_img = Image.open(live).convert("RGBA")
        return src_img, src_img.size
    if sk == "mockup":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == source_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel {source_id}")
        mockup_path = fs_ws.board_root(board_id) / catalog["style"]["reference_image"]
        if not mockup_path.exists():
            raise HTTPException(404, f"Mockup not found at {mockup_path}")
        x1, y1, x2, y2 = p["bbox"]
        crop = Image.open(mockup_path).convert("RGBA").crop((x1, y1, x2, y2))
        crop = crop.resize(tuple(p["target_size"]), Image.NEAREST)
        return crop, (p["target_size"][0], p["target_size"][1])
    if sk == "upload":
        upload_path = (
            fs_ws.board_root(board_id) / "workspace" / "frames" / "_uploads" / source_id
        )
        if not upload_path.exists():
            raise HTTPException(404, f"Upload {source_id!r} not found")
        src_img = Image.open(upload_path).convert("RGBA")
        return src_img, src_img.size
    raise HTTPException(400, f"Unknown source_kind {source_kind!r}")


def _cover_resize_nearest(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Uniform scale then center-crop so result is exactly tw×th (pixel-art friendly)."""
    iw, ih = img.size
    if iw <= 0 or ih <= 0 or tw <= 0 or th <= 0:
        return Image.new("RGBA", (max(tw, 1), max(th, 1)), (0, 0, 0, 0))
    scale = max(tw / iw, th / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    up = img.resize((nw, nh), Image.NEAREST)
    left = max(0, (nw - tw) // 2)
    top = max(0, (nh - th) // 2)
    return up.crop((left, top, left + tw, top + th))


def _pick_alternate_live_space_id(
    board_id: str,
    catalog: dict,
    source_id: str,
) -> str | None:
    """First catalog-order live space design whose id ≠ ``source_id``.

    Panel/upload/mockup sources never equal a space id, so any live space qualifies.
    If only one live space exists and its id equals ``source_id`` (e.g. future
    space-as-frame-source), returns ``None`` so the caller falls back to the
    rim-source interior.
    """
    try:
        cat_model = Catalog.from_dict(catalog)
    except Exception:
        return None
    store = bs.get_store()
    for d in cat_model.all_space_designs():
        rel = fs_ws.live_rel("spaces", d.id)
        if not store.exists(board_id, rel):
            continue
        if d.id != source_id:
            return d.id
    return None


@router.post("/users/{username}/board-games/{path_slug}/api/frame/propose")
async def api_frame_propose(
    request: Request,
    board_id: NestedBoardId,
    source_kind: str = Form(...),
    source_id: str = Form(...),
    candidate_count: int = Form(default=3),
    use_vision: bool = Form(default=True),
):
    """Atelier "Propose" entry point — enqueue a vision job.

    Returns ``{ "job_id": ... }`` on accepted; the UI subscribes to
    ``/events/jobs`` for progress and polls ``/api/frame/proposals/{job_id}``
    once the job goes terminal to fetch the candidate manifest.
    """
    if candidate_count < 1 or candidate_count > 5:
        raise HTTPException(400, "candidate_count must be in 1..5")
    source_kind = bf_frames.normalize_frame_source_kind(source_kind)
    if source_kind not in bf_frames.VALID_FRAME_SOURCE_KINDS:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")

    keys = deps.user_provider_api_keys(request)
    openai_key = keys.get("openai_key") or os.environ.get("OPENAI_API_KEY", "")
    if use_vision and not openai_key:
        # Don't reject — just log + degrade to deterministic. The Atelier
        # surfaces a banner in this case so the user knows to add a key.
        use_vision = False

    cost = 0.04 if (use_vision and openai_key) else 0.0
    job_id = deps.enqueue_pipeline_job(
        label=f"Propose frame ({source_kind}:{source_id})",
        operation="frame.propose",
        target=source_id,
        cost_estimate=cost,
        fn=deps.scoped_pipeline_callable(
            board_id,
            partial(
                pipeline_jobs.frame_propose,
                source_kind=source_kind,
                source_id=source_id,
                candidate_count=candidate_count,
                openai_key=openai_key or None,
                use_vision=use_vision,
            ),
        ),
    )
    return JSONResponse({"job_id": job_id, "use_vision": use_vision})


@router.get(
    "/users/{username}/board-games/{path_slug}/api/frame/proposals/{job_id}"
)
async def api_frame_proposals(
    request: Request, board_id: NestedBoardId, job_id: str,
):
    """Read the manifest written by a finished ``frame.propose`` job."""
    import json as _json

    d = _proposals_dir(board_id, job_id)
    manifest_p = d / "manifest.json"
    if not manifest_p.exists():
        raise HTTPException(404, f"No proposal manifest for job {job_id!r}")

    try:
        manifest = _json.loads(manifest_p.read_text())
    except Exception as e:
        raise HTTPException(500, f"Could not parse manifest: {e}") from None

    candidates = manifest.get("candidates") or []
    enriched = []
    for c in candidates:
        enriched.append({
            **c,
            "preview_url": _proposals_static_url(
                board_id, job_id, c.get("preview_filename", ""),
            ) if c.get("preview_filename") else None,
            "hole_mask_url": _proposals_static_url(
                board_id, job_id, c.get("hole_mask_filename", ""),
            ) if c.get("hole_mask_filename") else None,
            "rim_mask_url": _proposals_static_url(
                board_id, job_id, c.get("rim_mask_filename", ""),
            ) if c.get("rim_mask_filename") else None,
        })
    out = {**manifest, "candidates": enriched}
    return JSONResponse(out)


class FrameRefineBody(BaseModel):
    """Body for ``POST /api/frame/refine`` — resize proposal bbox (handle drag)."""

    job_id: str
    candidate_index: int
    bbox: tuple[int, int, int, int]
    source_kind: Literal["functional", "mockup", "upload"]
    source_id: str
    ring_px: int | None = None

    @field_validator("source_kind", mode="before")
    @classmethod
    def _normalize_refine_source_kind(cls, v: object) -> str:
        return bf_frames.normalize_frame_source_kind(str(v))

    @field_validator("bbox", mode="before")
    @classmethod
    def _bbox_tuple(cls, v):
        if isinstance(v, (list, tuple)) and len(v) == 4:
            return tuple(int(x) for x in v)
        raise ValueError("bbox must be four integers")


@router.post("/users/{username}/board-games/{path_slug}/api/frame/refine")
async def api_frame_refine(
    request: Request, board_id: NestedBoardId, body: FrameRefineBody,
):
    """Apply ``fit_to_window`` to a stored proposal and rewrite masks + preview."""
    d = _proposals_dir(board_id, body.job_id)
    manifest_p = d / "manifest.json"
    if not manifest_p.exists():
        raise HTTPException(404, f"No proposal manifest for job {body.job_id!r}")
    try:
        manifest = _json_std.loads(manifest_p.read_text())
    except Exception as e:
        raise HTTPException(500, f"Bad manifest: {e}") from None

    if (
        not bf_frames.frame_source_kinds_match(
            manifest.get("source_kind"), body.source_kind,
        )
        or manifest.get("source_id") != body.source_id
    ):
        raise HTTPException(400, "source_kind / source_id do not match the proposal run")

    cands = manifest.get("candidates") or []
    if body.candidate_index < 0 or body.candidate_index >= len(cands):
        raise HTTPException(404, f"Candidate index {body.candidate_index} out of range")
    cand = cands[body.candidate_index]

    sw, sh = int(manifest["source_size"][0]), int(manifest["source_size"][1])
    catalog = deps.load_board_catalog(board_id)
    src_img, src_size = _load_atelier_source(
        board_id, catalog, body.source_kind, body.source_id,
    )
    if src_size != (sw, sh):
        raise HTTPException(
            400,
            f"Source size {src_size} does not match proposal {sw}×{sh}",
        )

    hole_f = cand.get("hole_mask_filename")
    rim_f = cand.get("rim_mask_filename")
    prev_f = cand.get("preview_filename")
    if not hole_f or not rim_f or not prev_f:
        raise HTTPException(500, "Candidate manifest entry is incomplete")

    geo = bf_frames_inference.CandidateGeometry(
        bbox=tuple(int(x) for x in cand["bbox"]),
        ring_px=int(cand["ring_px"]),
        hole_mask=Image.open(d / hole_f).convert("L"),
        rim_mask=Image.open(d / rim_f).convert("L"),
        score=float(cand["score"]),
        notes=str(cand.get("notes") or ""),
    )
    rp = body.ring_px if body.ring_px is not None else geo.ring_px
    rp = max(2, min(rp, min(src_size) // 2 - 1))
    geo = replace(geo, ring_px=rp)

    x1, y1, x2, y2 = body.bbox
    x1 = max(0, min(sw - 2, int(x1)))
    y1 = max(0, min(sh - 2, int(y1)))
    x2 = max(x1 + 2, min(sw, int(x2)))
    y2 = max(y1 + 2, min(sh, int(y2)))
    if x2 - x1 <= 2 * rp + 2 or y2 - y1 <= 2 * rp + 2:
        raise HTTPException(
            400,
            "Bounding box too small for current ring thickness — "
            "widen the frame or reduce ring thickness.",
        )
    bbox_adj = (x1, y1, x2, y2)

    refined = bf_frames_inference.fit_to_window(
        geo,
        bbox=bbox_adj,
        source_size=src_size,
    )

    refined.hole_mask.save(d / hole_f)
    refined.rim_mask.save(d / rim_f)
    overlay = bf_frames_inference.overlay_for_review(
        src_img, refined.rim_mask, refined.hole_mask,
    )
    overlay.save(d / prev_f)

    cand["bbox"] = list(refined.bbox)
    cand["ring_px"] = refined.ring_px
    cand["notes"] = refined.notes
    cands[body.candidate_index] = cand
    manifest["candidates"] = cands
    manifest_p.write_text(_json_std.dumps(manifest, indent=2))

    ts = asset_urls.wall_clock_ms()
    preview_url = f"{_proposals_static_url(board_id, body.job_id, prev_f)}?t={ts}"
    return JSONResponse({
        "ok": True,
        "bbox": list(refined.bbox),
        "ring_px": refined.ring_px,
        "notes": refined.notes,
        "preview_url": preview_url,
    })


class FrameCommitBody(BaseModel):
    """Body for ``POST /api/frame/commit``.

    A commit can land in one of two ways:

      * From a vision proposal: pass ``job_id`` + ``candidate_index``.
        The server reads the proposal's hole/rim masks, regenerates a
        nine-slice, and adopts.
      * From a deterministic ring: pass ``source_kind`` + ``source_id``
        + ``ring_px``. Equivalent to the legacy adopt path; this is the
        Atelier's "no vision" fallback and is what the side-panel link
        triggers when there are no proposals.

    ``enable_after`` (default true) flips ``catalog.frame.enabled`` on
    so the rim shows immediately. ``regen_panels`` (default true) is
    Approach D — when true the server enqueues ``frame.reapply`` and
    returns the ``regen_job_id`` so the UI can attach progress to it.

    ``regen_single_panel_id`` — when set (and typically ``regen_panels``
    is false), enqueue ``frame.reapply_one`` for that panel id only so
    the Atelier can regenerate one tile then redirect to the board.
    """

    source_kind: Literal["functional", "mockup", "upload"]
    source_id: str
    ring_px: int

    job_id: str | None = None
    candidate_index: int | None = None

    enable_after: bool = True
    regen_panels: bool = True
    regen_single_panel_id: str | None = None

    @field_validator("source_kind", mode="before")
    @classmethod
    def _normalize_commit_source_kind(cls, v: object) -> str:
        return bf_frames.normalize_frame_source_kind(str(v))


@router.post("/users/{username}/board-games/{path_slug}/api/frame/commit")
async def api_frame_commit(
    request: Request, board_id: NestedBoardId, body: FrameCommitBody,
):
    """Atelier "Commit" — write FrameInstance + (optionally) enqueue Approach D.

    Returns ``{frame_id, regen_job_id?}``. The UI transitions to its
    in-progress view and consumes the regen job over SSE.
    """
    import json as _json

    if body.ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    catalog = deps.load_board_catalog(board_id)

    src_img, src_size = _load_atelier_source(
        board_id, catalog, body.source_kind, body.source_id,
    )

    model_id = "deterministic"
    prompt_hash: str | None = None
    candidate_index: int | None = None
    proposal_masks: tuple[Image.Image, Image.Image] | None = None

    if body.job_id and body.candidate_index is not None:
        d = _proposals_dir(board_id, body.job_id)
        manifest_p = d / "manifest.json"
        if not manifest_p.exists():
            raise HTTPException(404, f"No proposal manifest for job {body.job_id!r}")
        try:
            manifest = _json.loads(manifest_p.read_text())
        except Exception as e:
            raise HTTPException(500, f"Bad manifest: {e}") from None
        cands = manifest.get("candidates") or []
        if body.candidate_index < 0 or body.candidate_index >= len(cands):
            raise HTTPException(404, f"Candidate index {body.candidate_index} out of range")
        cand = cands[body.candidate_index]
        candidate_index = int(body.candidate_index)
        model_id = manifest.get("model_id") or model_id
        prompt_hash = manifest.get("prompt_hash")

        bb = cand.get("bbox")
        hole_f = cand.get("hole_mask_filename")
        rim_f = cand.get("rim_mask_filename")
        if isinstance(bb, (list, tuple)) and len(bb) == 4 and hole_f and rim_f:
            x1, y1, x2, y2 = (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3]))
            W, H = src_img.size
            x1 = max(0, min(W, x1))
            y1 = max(0, min(H, y1))
            x2 = max(0, min(W, x2))
            y2 = max(0, min(H, y2))
            if x2 > x1 and y2 > y1:
                hole_p = d / str(hole_f)
                rim_p = d / str(rim_f)
                if hole_p.exists() and rim_p.exists():
                    proposal_masks = (
                        Image.open(hole_p).convert("L").crop((x1, y1, x2, y2)),
                        Image.open(rim_p).convert("L").crop((x1, y1, x2, y2)),
                    )
                src_img = src_img.crop((x1, y1, x2, y2))
                src_size = src_img.size

    if body.ring_px * 2 >= min(src_size):
        raise HTTPException(
            400, f"ring_px={body.ring_px} too thick for source {src_size}"
        )

    from domains.spaces import frames_repository as frames_repo

    with bf_config.scope_board(board_id):
        slice_ = bf_frames.extract_9slice(src_img, body.ring_px)
        if proposal_masks is not None:
            ho, ri = proposal_masks
            if ho.size == src_size == ri.size:
                slice_.hole_mask = ho
                slice_.rim_mask = ri
        instance = bf_frames.FrameInstance(
            ring_px=int(body.ring_px),
            source_kind=body.source_kind,
            source_id=body.source_id,
            source_size=src_size,
            model_id=model_id,
            prompt_hash=prompt_hash,
            candidate_index=candidate_index,
            notes="committed via Atelier",
        )
        bf_frames.adopt_house_frame(slice_, instance)
        view = frames_repo.replace_active(board_id, instance=instance)

    if body.enable_after:
        svc_boards.set_frame_flags(board_id, enabled=True, apply_to_panels=True)

    regen_job_id: str | None = None
    keys = deps.user_provider_api_keys(request)

    if body.regen_single_panel_id:
        pid = body.regen_single_panel_id.strip()
        panel_rows = catalog.get("feature_panels", {}).get("panels", [])
        panel_ids = [p["id"] for p in panel_rows]
        if pid not in panel_ids:
            raise HTTPException(400, f"Unknown panel {pid!r}")
        live_rel = fs_ws.live_rel("panels", pid)
        if not bs.get_store().exists(board_id, live_rel):
            raise HTTPException(
                400,
                f"No live art for panel {pid!r} — generate it before reapply.",
            )
        regen_cost = pipeline_jobs.estimate_generate_one("panels", pid)
        regen_job_id = deps.enqueue_pipeline_job(
            label=f"Reapply frame to panel {pid}",
            operation="frame.reapply_one",
            target=pid,
            cost_estimate=regen_cost,
            fn=deps.scoped_pipeline_callable(
                board_id,
                partial(pipeline_jobs.frame_reapply_one, panel_id=pid, **keys),
            ),
        )
    elif body.regen_panels:
        # Conservative panel-count-based estimate: actual cost is computed
        # inside the worker as it bills each provider call. Per-panel
        # estimate matches what generate_one shows in the side panel so
        # the Atelier and the side panel agree.
        n_panels = len(catalog.get("feature_panels", {}).get("panels", []))
        regen_cost = pipeline_jobs.estimate_generate_one("panels") * n_panels

        regen_job_id = deps.enqueue_pipeline_job(
            label=f"Reapply frame to {n_panels} panel{'s' if n_panels != 1 else ''}",
            operation="frame.reapply",
            target=board_id,
            cost_estimate=regen_cost,
            fn=deps.scoped_pipeline_callable(
                board_id,
                partial(pipeline_jobs.frame_reapply, **keys),
            ),
        )

    return JSONResponse({
        "ok": True,
        "frame_id": view.id,
        "ring_px": body.ring_px,
        "source_kind": body.source_kind,
        "source_id": body.source_id,
        "regen_job_id": regen_job_id,
        "regen_single_panel": bool(body.regen_single_panel_id),
    })


@router.post("/users/{username}/board-games/{path_slug}/api/frame/upload")
async def api_frame_upload(
    request: Request, board_id: NestedBoardId, file: UploadFile = File(...),
):
    """Persist an uploaded image as a Propose source for the Atelier."""
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image (PNG or JPEG).")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload received.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        raise HTTPException(400, "Could not read image — not a valid PNG or JPEG.")

    target_dir = (
        fs_ws.board_root(board_id) / "workspace" / "frames" / "_uploads"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
    if not safe_name.lower().endswith((".png", ".jpg", ".jpeg")):
        safe_name = f"{safe_name}.png"
    target_path = target_dir / safe_name
    img.save(target_path, format="PNG")

    bp = board_prefix(board_id)
    return JSONResponse({
        "ok": True,
        "source_id": safe_name,
        "size": list(img.size),
        "url": f"{bp}/asset/frames/_uploads/{safe_name}",
    })


def _board_home_redirect(board_id: str) -> str:
    return f"{board_prefix(board_id)}/"


def _board_preview_redirect(board_id: str) -> str:
    return f"{board_prefix(board_id)}/preview"


async def _action_analyze(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    user = current_user(request)
    openai_key = (user.openai_api_key if user else "") or os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(
            400,
            "No OpenAI API key found. Save one in Account → Connections → OpenAI / ChatGPT."
        )
    job_id = deps.enqueue_pipeline_job(
        label="Analyze mockup with GPT-4o",
        operation="analyze", target=board_id,
        cost_estimate=pipeline_jobs.ANALYZE_COST_USD,
        fn=deps.scoped_pipeline_callable(
            board_id, partial(pipeline_jobs.analyze, openai_key=openai_key),
        ),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/analyze")
async def action_analyze_nested(request: Request, board_id: NestedBoardId):
    return await _action_analyze(request, board_id)


async def _action_style(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    job_id = deps.enqueue_pipeline_job(
        label="Extract style from mockup",
        operation="style", target=board_id,
        cost_estimate=pipeline_jobs.estimate_style(),
        fn=deps.scoped_pipeline_callable(board_id, pipeline_jobs.style),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/style")
async def action_style_nested(request: Request, board_id: NestedBoardId):
    return await _action_style(request, board_id)


async def _action_generate_missing_all(
    request: Request, board_id: str,
) -> JSONResponse | RedirectResponse:
    catalog = deps.load_board_catalog(board_id)
    missing_spaces = svc_spaces.missing_space_ids(board_id, catalog)
    missing_panels = svc_spaces.missing_panel_ids(board_id, catalog)
    total = len(missing_spaces) + len(missing_panels)
    keys = deps.user_provider_api_keys(request)
    job_id = deps.enqueue_pipeline_job(
        label=f"Generate {total} missing asset{'s' if total != 1 else ''}",
        operation="generate.all", target=board_id,
        cost_estimate=pipeline_jobs.estimate_generate_all(
            len(missing_spaces), len(missing_panels)
        ),
        fn=deps.scoped_pipeline_callable(
            board_id, partial(pipeline_jobs.generate_all, **keys),
        ),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/generate-missing/all")
async def action_generate_missing_all_nested(request: Request, board_id: NestedBoardId):
    return await _action_generate_missing_all(request, board_id)


async def _action_states(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    job_id = deps.enqueue_pipeline_job(
        label="Build active states",
        operation="states", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_jobs.states),
    )
    return deps.job_or_redirect_response(
        request, job_id, redirect_to=_board_preview_redirect(board_id),
    )


@router.post("/users/{username}/board-games/{path_slug}/actions/states")
async def action_states_nested(request: Request, board_id: NestedBoardId):
    return await _action_states(request, board_id)


async def _action_preview(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    job_id = deps.enqueue_pipeline_job(
        label="Composite preview",
        operation="preview", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_jobs.preview),
    )
    return deps.job_or_redirect_response(
        request, job_id, redirect_to=_board_preview_redirect(board_id),
    )


@router.post("/users/{username}/board-games/{path_slug}/actions/preview")
async def action_preview_nested(request: Request, board_id: NestedBoardId):
    return await _action_preview(request, board_id)


async def _action_export(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    job_id = deps.enqueue_pipeline_job(
        label="Export approved assets",
        operation="export", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_jobs.export),
    )
    return deps.job_or_redirect_response(
        request, job_id, redirect_to=_board_preview_redirect(board_id),
    )


@router.post("/users/{username}/board-games/{path_slug}/actions/export")
async def action_export_nested(request: Request, board_id: NestedBoardId):
    return await _action_export(request, board_id)


@router.get("/users/{username}/board-games/{path_slug}/export/project-bundle.zip")
def download_project_bundle_zip(board_id: NestedBoardId):
    """Portable ``project.json`` + ``assets/`` via ``domains.boards.exporter``.

    The bundle tree and intermediate zip exist only inside a process-local
    ``tempfile.TemporaryDirectory``; the handler returns bytes in memory after
    the directory is destroyed (no accumulation under the board store).

    This is **not** the pipeline ``POST …/actions/export`` (approved tiles to
    ``export/``); that job stays separate.
    """
    cat = deps.load_board_catalog(board_id)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        res = run_board_export(
            board_id,
            cat,
            options=BoardExportOptions(store=bs.get_store(), bundle_root=root),
        )
        if not res.ok:
            raise HTTPException(422, detail={"export_errors": list(res.errors)})
        arc_path = shutil.make_archive(str(root / "bundle"), "zip", root_dir=str(root))
        data = Path(arc_path).read_bytes()
    safe = board_id.replace("-", "")[:12] or "board"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="project-export-{safe}.zip"',
            "Cache-Control": "no-store",
        },
    )


async def _action_regen_one(
    request: Request, board_id: str, category: str, asset_id: str,
    prompt_override: str | None,
) -> JSONResponse | RedirectResponse:
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    p = (prompt_override or "").strip() or None
    keys = deps.user_provider_api_keys(request)
    job_id = deps.enqueue_pipeline_job(
        label=f"Regenerate {asset_id}",
        operation=f"regen.{category}", target=asset_id,
        cost_estimate=pipeline_jobs.estimate_generate_one(category, asset_id),
        fn=deps.scoped_pipeline_callable(
            board_id,
            partial(
                pipeline_jobs.generate_one,
                category=category,
                asset_id=asset_id,
                prompt_override=p,
                **keys,
            ),
        ),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/regen/{category}/{asset_id}")
async def action_regen_one_nested(
    request: Request, board_id: NestedBoardId, category: str, asset_id: str,
    prompt_override: str | None = Form(default=None),
):
    return await _action_regen_one(request, board_id, category, asset_id, prompt_override)


async def _action_clean_one(
    request: Request, board_id: str, category: str, asset_id: str,
) -> JSONResponse | RedirectResponse:
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    job_id = deps.enqueue_pipeline_job(
        label=f"Clean {asset_id}",
        operation=f"clean.{category}", target=asset_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(
            board_id,
            partial(pipeline_jobs.clean_one, category=category, asset_id=asset_id),
        ),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/clean/{category}/{asset_id}")
async def action_clean_one_nested(request: Request, board_id: NestedBoardId, category: str, asset_id: str):
    return await _action_clean_one(request, board_id, category, asset_id)


async def _api_put_generation(request: Request, board_id: str) -> JSONResponse:
    body = await request.json()
    try:
        new_block = svc_boards.write_generation(board_id, body)
    except svc_boards.GenerationValidationError as e:
        raise HTTPException(400, str(e)) from None
    return JSONResponse({"settings": new_block})


@router.put("/users/{username}/board-games/{path_slug}/api/generation")
async def api_put_generation_nested(request: Request, board_id: NestedBoardId):
    return await _api_put_generation(request, board_id)


def _api_rename_board(request: Request, board_id: str, project_name: str) -> JSONResponse:
    try:
        summary = svc_boards.rename_board(require_user(request).id, board_id, project_name)
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Board not found") from None
    except svc_boards.InvalidBoardId as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return JSONResponse({"ok": True, "project": summary.project})


@router.post("/users/{username}/board-games/{path_slug}/api/rename")
def api_rename_board_nested(
    request: Request, board_id: NestedBoardId, project_name: str = Form(...),
):
    return _api_rename_board(request, board_id, project_name)


class SpaceReassignBody(BaseModel):
    from_design_id: str
    position_ref: str
    to_design_id: str | None = None
    new_design_id: str | None = None
    asset_policy: Literal["copy_live", "empty"] = "empty"


@router.post("/users/{username}/board-games/{path_slug}/api/spaces/reassign")
def api_space_reassign(
    board_id: NestedBoardId, body: SpaceReassignBody,
) -> JSONResponse:
    with bf_config.scope_board(board_id):
        try:
            out = svc_boards.reassign_space_position(
                board_id,
                from_design_id=body.from_design_id,
                position_ref=body.position_ref,
                to_design_id=body.to_design_id,
                new_design_id=body.new_design_id,
                asset_policy=body.asset_policy,
            )
        except svc_boards.SpaceDesignReassignError as e:
            raise HTTPException(400, str(e)) from None
    return JSONResponse(
        {
            "ok": True,
            "result": out["result"],
            "design_id": out["design_id"],
        }
    )


# ────────────────────────── board CRUD (create / clone / delete) ──────────────────────────


class CloneBoardBody(BaseModel):
    path_slug: str | None = None
    project_name: str | None = None


@router.post("/api/boards")
async def api_create_board(
    request: Request,
    board_id: str = Form(...),
    project_name: str | None = Form(default=None),
):
    user = require_user(request)
    bid = bf_boards.slugify(board_id)
    try:
        summary = svc_boards.create_board(
            bid,
            owner_user_id=user.id,
            project_name=project_name or board_id,
        )
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardExists:
        raise HTTPException(409, f"Board {bid!r} already exists")
    base = deps.canonical_board_base_path(summary.id)
    return JSONResponse({"id": summary.id, "url": f"{base}/"})


@router.post("/api/boards/{board_id}/clone")
async def api_clone_board(
    request: Request,
    board_id: str,
    body: CloneBoardBody | None = None,
):
    user = require_user(request)
    payload = body or CloneBoardBody()
    try:
        summary = svc_boards.clone_board(
            user.id,
            board_id,
            path_slug=payload.path_slug,
            project_name=payload.project_name,
        )
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Unknown board")
    except svc_boards.BoardExists as e:
        raise HTTPException(409, str(e))
    base = deps.canonical_board_base_path(summary.id)
    return JSONResponse({"id": summary.id, "url": f"{base}/"}, status_code=201)


@router.delete("/api/boards/{board_id}")
def api_delete_board(request: Request, board_id: str):
    user = require_user(request)
    try:
        svc_boards.delete_board(user.id, board_id)
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Unknown board")
    return JSONResponse({"deleted": board_id})

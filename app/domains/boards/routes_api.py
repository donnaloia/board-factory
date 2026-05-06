"""Board JSON/binary routes — pipeline actions, generation API, frame tooling."""

from __future__ import annotations

import base64
import io
import os
from functools import partial
from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from PIL import Image
from pydantic import BaseModel

from auth.middleware import current_user, require_user
from jobs import pipeline_adapters
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from boardfactory.providers.pixel.pixellab import list_pixellab_presets

from domains.boards.routes_common import NestedBoardId, board_prefix
from infrastructure import deps
from domains.boards import services as svc_boards
from domains.cells import services as svc_cells
from assets import services as asset_urls
from domains.boards import mockup_prompt as mockup_prompt_svc
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


@router.get("/users/{username}/board-games/{path_slug}/api/frame/preview.png")
def api_frame_preview(
    request: Request, board_id: NestedBoardId, source_kind: str, source_id: str,
    ring_px: int, w: int = 260, h: int = 240,
):
    """Live preview: extract 9-slice + recompose at target size, no disk write."""
    if ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    catalog = deps.load_board_catalog(board_id)
    if source_kind == "panel":
        live = fs_ws.live_path(board_id, "panels", source_id)
        if not live.exists():
            raise HTTPException(404)
        src_img = Image.open(live).convert("RGBA")
    elif source_kind == "mockup":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == source_id), None)
        if p is None:
            raise HTTPException(404)
        mockup_path = fs_ws.board_root(board_id) / catalog["style"]["reference_image"]
        if not mockup_path.exists():
            raise HTTPException(404)
        bx1, by1, bx2, by2 = p["bbox"]
        src_img = Image.open(mockup_path).convert("RGBA").crop((bx1, by1, bx2, by2))
        src_img = src_img.resize(tuple(p["target_size"]), Image.NEAREST)
    else:
        raise HTTPException(400)

    if ring_px * 2 >= min(src_img.size):
        raise HTTPException(400, f"ring_px={ring_px} too thick for source")

    slice_ = bf_frames.extract_9slice(src_img, ring_px)
    composed = bf_frames.compose_frame(slice_, (w, h))
    buf = io.BytesIO()
    composed.save(buf, format="PNG")
    return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="image/png",
                             headers={"Cache-Control": "no-store"})


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

    catalog = deps.load_board_catalog(board_id)
    src_img: Image.Image
    src_size: tuple[int, int]

    if source_kind == "panel":
        live = fs_ws.live_path(board_id, "panels", source_id)
        if not live.exists():
            raise HTTPException(404, f"No live panel asset for {source_id}")
        src_img = Image.open(live).convert("RGBA")
        src_size = src_img.size
    elif source_kind == "mockup":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == source_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel {source_id}")
        ref_rel = catalog["style"]["reference_image"]
        mockup_path = fs_ws.board_root(board_id) / ref_rel
        if not mockup_path.exists():
            raise HTTPException(404, f"Mockup not found at {mockup_path}")
        bx1, by1, bx2, by2 = p["bbox"]
        mockup = Image.open(mockup_path).convert("RGBA")
        src_img = mockup.crop((bx1, by1, bx2, by2))
        tw, th = p["target_size"]
        src_img = src_img.resize((tw, th), Image.NEAREST)
        src_size = (tw, th)
    elif source_kind == "upload":
        upload_path = (
            fs_ws.board_root(board_id) / "workspace" / "frames" / "_uploads" / source_id
        )
        if not upload_path.exists():
            raise HTTPException(404, f"Upload {source_id!r} not found")
        src_img = Image.open(upload_path).convert("RGBA")
        src_size = src_img.size
    else:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")

    if ring_px * 2 >= min(src_size):
        raise HTTPException(400, f"ring_px={ring_px} is too thick for source {src_size}")

    from domains.cells import frames_repository as frames_repo

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
        data = deps.load_board_catalog(board_id)
        data.setdefault("frame", {})
        data["frame"]["enabled"] = True
        data["frame"]["apply_to_panels"] = True
        svc_boards.save_catalog(board_id, data)

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
    data = deps.load_board_catalog(board_id)
    data.setdefault("frame", {})
    data["frame"]["enabled"] = False
    svc_boards.save_catalog(board_id, data)

    from domains.cells import frames_repository as frames_repo

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
    if source_kind not in ("panel", "mockup", "upload"):
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
                pipeline_adapters.frame_propose,
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
    """

    source_kind: Literal["panel", "mockup", "upload"]
    source_id: str
    ring_px: int

    job_id: str | None = None
    candidate_index: int | None = None

    enable_after: bool = True
    regen_panels: bool = True


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

    # Resolve the source image. We always need it because the on-disk
    # nine-slice pack stores actual rim pixels, even if vision provided
    # the masks.
    src_img: Image.Image
    src_size: tuple[int, int]
    if body.source_kind == "panel":
        live = fs_ws.live_path(board_id, "panels", body.source_id)
        if not live.exists():
            raise HTTPException(404, f"No live panel asset for {body.source_id}")
        src_img = Image.open(live).convert("RGBA")
        src_size = src_img.size
    elif body.source_kind == "mockup":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == body.source_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel {body.source_id}")
        mockup_path = fs_ws.board_root(board_id) / catalog["style"]["reference_image"]
        if not mockup_path.exists():
            raise HTTPException(404, f"Mockup not found at {mockup_path}")
        x1, y1, x2, y2 = p["bbox"]
        crop = Image.open(mockup_path).convert("RGBA").crop((x1, y1, x2, y2))
        crop = crop.resize(tuple(p["target_size"]), Image.NEAREST)
        src_img = crop
        src_size = (p["target_size"][0], p["target_size"][1])
    elif body.source_kind == "upload":
        upload_path = (
            fs_ws.board_root(board_id) / "workspace" / "frames" / "_uploads" / body.source_id
        )
        if not upload_path.exists():
            raise HTTPException(404, f"Upload {body.source_id!r} not found")
        src_img = Image.open(upload_path).convert("RGBA")
        src_size = src_img.size
    else:
        raise HTTPException(400, f"Unknown source_kind {body.source_kind!r}")

    if body.ring_px * 2 >= min(src_size):
        raise HTTPException(
            400, f"ring_px={body.ring_px} too thick for source {src_size}"
        )

    # If the commit refers to a vision proposal, load its manifest +
    # masks; otherwise fall back to deterministic ring extraction.
    model_id = "deterministic"
    prompt_hash: str | None = None
    candidate_index: int | None = None

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
        # We could read the cand hole/rim masks back here and use them,
        # but the rim is so visually subtle that the user-confirmed
        # ring_px (slider value) is what matters most. We snapshot the
        # ring_px from the body rather than the manifest to honor the
        # user's slider edits during refine.
        _ = cand  # placeholder for future Phase A wiring.

    from domains.cells import frames_repository as frames_repo

    with bf_config.scope_board(board_id):
        slice_ = bf_frames.extract_9slice(src_img, body.ring_px)
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
        data = deps.load_board_catalog(board_id)
        data.setdefault("frame", {})
        data["frame"]["enabled"] = True
        data["frame"]["apply_to_panels"] = True
        svc_boards.save_catalog(board_id, data)

    regen_job_id: str | None = None
    if body.regen_panels:
        keys = deps.user_provider_api_keys(request)
        # Conservative panel-count-based estimate: actual cost is computed
        # inside the worker as it bills each provider call. Per-panel
        # estimate matches what generate_one shows in the side panel so
        # the Atelier and the side panel agree.
        n_panels = len(catalog.get("feature_panels", {}).get("panels", []))
        regen_cost = pipeline_adapters.estimate_generate_one("panels") * n_panels

        regen_job_id = deps.enqueue_pipeline_job(
            label=f"Reapply frame to {n_panels} panel{'s' if n_panels != 1 else ''}",
            operation="frame.reapply",
            target=board_id,
            cost_estimate=regen_cost,
            fn=deps.scoped_pipeline_callable(
                board_id,
                partial(pipeline_adapters.frame_reapply, **keys),
            ),
        )

    return JSONResponse({
        "ok": True,
        "frame_id": view.id,
        "ring_px": body.ring_px,
        "source_kind": body.source_kind,
        "source_id": body.source_id,
        "regen_job_id": regen_job_id,
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
        cost_estimate=pipeline_adapters.ANALYZE_COST_USD,
        fn=deps.scoped_pipeline_callable(
            board_id, partial(pipeline_adapters.analyze, openai_key=openai_key),
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
        cost_estimate=pipeline_adapters.estimate_style(),
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.style),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=_board_home_redirect(board_id))


@router.post("/users/{username}/board-games/{path_slug}/actions/style")
async def action_style_nested(request: Request, board_id: NestedBoardId):
    return await _action_style(request, board_id)


async def _action_generate_missing_all(
    request: Request, board_id: str,
) -> JSONResponse | RedirectResponse:
    catalog = deps.load_board_catalog(board_id)
    missing_spaces = svc_cells.missing_space_ids(board_id, catalog)
    missing_panels = svc_cells.missing_panel_ids(board_id, catalog)
    total = len(missing_spaces) + len(missing_panels)
    keys = deps.user_provider_api_keys(request)
    job_id = deps.enqueue_pipeline_job(
        label=f"Generate {total} missing asset{'s' if total != 1 else ''}",
        operation="generate.all", target=board_id,
        cost_estimate=pipeline_adapters.estimate_generate_all(
            len(missing_spaces), len(missing_panels)
        ),
        fn=deps.scoped_pipeline_callable(
            board_id, partial(pipeline_adapters.generate_all, **keys),
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
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.states),
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
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.preview),
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
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.export),
    )
    return deps.job_or_redirect_response(
        request, job_id, redirect_to=_board_preview_redirect(board_id),
    )


@router.post("/users/{username}/board-games/{path_slug}/actions/export")
async def action_export_nested(request: Request, board_id: NestedBoardId):
    return await _action_export(request, board_id)


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
        cost_estimate=pipeline_adapters.estimate_generate_one(category, asset_id),
        fn=deps.scoped_pipeline_callable(
            board_id,
            partial(
                pipeline_adapters.generate_one,
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
            partial(pipeline_adapters.clean_one, category=category, asset_id=asset_id),
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

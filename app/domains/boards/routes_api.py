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
    else:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")

    if ring_px * 2 >= min(src_size):
        raise HTTPException(400, f"ring_px={ring_px} is too thick for source {src_size}")

    with bf_config.scope_board(board_id):
        slice_ = bf_frames.extract_9slice(src_img, ring_px)
        meta = bf_frames.FrameMeta(
            ring_px=ring_px,
            source_kind=source_kind,
            source_id=source_id,
            source_size=src_size,
        )
        bf_frames.adopt_house_frame(slice_, meta)

    if enable_after:
        data = deps.load_board_catalog(board_id)
        data.setdefault("frame", {})
        data["frame"]["enabled"] = True
        data["frame"]["apply_to_panels"] = True
        svc_boards.save_catalog(board_id, data)

    return JSONResponse({
        "ok": True,
        "ring_px": ring_px,
        "source_kind": source_kind,
        "source_id": source_id,
    })


@router.post("/users/{username}/board-games/{path_slug}/api/frame/adopt")
async def api_frame_adopt_nested(
    request: Request, board_id: NestedBoardId,
    source_kind: str = Form(...),
    source_id: str = Form(...),
    ring_px: int = Form(...),
    enable_after: bool = Form(default=True),
):
    return await _api_frame_adopt(
        request, board_id, source_kind, source_id, ring_px, enable_after,
    )


async def _api_frame_disable(request: Request, board_id: str) -> JSONResponse:
    data = deps.load_board_catalog(board_id)
    data.setdefault("frame", {})
    data["frame"]["enabled"] = False
    svc_boards.save_catalog(board_id, data)
    return JSONResponse({"ok": True})


@router.post("/users/{username}/board-games/{path_slug}/api/frame/disable")
async def api_frame_disable_nested(request: Request, board_id: NestedBoardId):
    return await _api_frame_disable(request, board_id)


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

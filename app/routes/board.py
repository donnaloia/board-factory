"""Per-board HTTP routes: views, pipeline actions, cell + asset APIs."""

from __future__ import annotations

import base64
import io
import os
from functools import partial
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from PIL import Image

import auth
import cost_ledger
import pipeline_adapters
import spec_data
from board_svg import render_board_svg, render_spec_svg
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from boardfactory.providers.pixel.pixellab import list_pixellab_presets

from routes import deps
from services import asset_urls
from services import boards as svc_boards
from services import catalog as svc_catalog
from services import cells as svc_cells
from services import mockup_prompt as mockup_prompt_svc
from storage import board_store as bs
from storage.fs import workspace as fs_ws

router = APIRouter()

NestedBoardId = Annotated[str, Depends(deps.require_nested_board)]


# ── helpers ───────────────────────────────────────────────────────────


def _board_prefix(board_id: str) -> str:
    return deps.board_http_prefix(board_id)


# ═══ GET: canonical nested paths; legacy /b/… is 307 at end of this file ═══


@router.get("/users/{username}/board-games/{path_slug}/", response_class=HTMLResponse)
def board_view(request: Request, board_id: NestedBoardId):
    if not fs_ws.has_palette(board_id):
        return RedirectResponse(f"{_board_prefix(board_id)}/setup", status_code=303)

    catalog = deps.load_board_catalog(board_id)
    stats = svc_cells.collect_board_stats(board_id, catalog)
    space_status = stats.space_status
    panel_status = stats.panel_status
    cp_status = stats.centerpiece_status
    n_designs = stats.designs_total
    n_panels = stats.panels_total
    designs_done = stats.designs_done
    panels_done = stats.panels_done
    missing_space_ids = stats.missing_space_ids
    missing_panel_ids = stats.missing_panel_ids
    n_missing_designs = len(missing_space_ids)
    n_missing_panels = len(missing_panel_ids)
    generated_designs = n_designs - n_missing_designs

    designs_list = catalog.get("board_spaces", {}).get("designs", [])
    total_positions = sum(len(d.get("positions", [])) for d in designs_list)
    missing_positions = sum(
        len(d.get("positions", [])) for d in designs_list
        if d["id"] in missing_space_ids
    )
    generated_positions = total_positions - missing_positions

    all_generate_estimate = pipeline_adapters.estimate_generate_all(
        n_missing_designs, n_missing_panels
    )
    n_missing_all = n_missing_designs + n_missing_panels
    n_generated_all = generated_designs + (n_panels - n_missing_panels)

    frame_overlay_url = None
    frame_block = catalog.get("frame", {}) or {}
    if frame_block.get("enabled") and frame_block.get("apply_to_panels", True):
        with bf_config.set_active_board(board_id):
            if bf_frames.has_house_frame():
                frame_overlay_url = f"{_board_prefix(board_id)}/frame.png"

    svg_markup = render_board_svg(
        catalog, space_status, panel_status, cp_status,
        frame_overlay_url=frame_overlay_url,
    )

    user = getattr(request.state, "user", None)
    has_openai_key = bool(
        (user and user.openai_api_key)
        or os.environ.get("OPENAI_API_KEY", "")
    )

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "board_size": catalog["board_size"],
        "svg_markup": svg_markup,
        "has_openai_key": has_openai_key,
        "analyze_cost": pipeline_adapters.ANALYZE_COST_USD,
        "stats": {
            "designs_total": n_designs,
            "designs_done": designs_done,
            "panels_total": n_panels,
            "panels_done": panels_done,
            "centerpiece_done": cp_status.approved,
        },
        "all_generation": {
            "missing": n_missing_all,
            "generated": n_generated_all,
            "total": n_designs + n_panels,
            "missing_spaces": n_missing_designs,
            "missing_panels": n_missing_panels,
            "estimate": all_generate_estimate,
            "label": (
                "All assets generated" if n_missing_all == 0
                else "Generate all spaces & UI" if n_generated_all == 0
                else "Generate missing spaces"
            ),
        },
        "generation": svc_catalog.read_generation(catalog),
    })
    return request.app.state.templates.TemplateResponse(request, "board.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/setup", response_class=HTMLResponse)
def setup_view(request: Request, board_id: NestedBoardId):
    mockup_present, mockup_rel = svc_boards.mockup_present(board_id)
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "mockup_present": mockup_present,
        "mockup_rel": mockup_rel,
        "mockup_ready_hint": request.query_params.get("mockup_ready") == "1",
    })
    return request.app.state.templates.TemplateResponse(request, "setup.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/spec", response_class=HTMLResponse)
def spec_view(request: Request, board_id: NestedBoardId):
    """Live tech spec from the board's catalog + the shared prose markdown."""
    catalog = deps.load_board_catalog(board_id)
    prose = deps.load_spec_prose_sections()
    user = getattr(request.state, "user", None)
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "summary": spec_data.header_summary(catalog),
        "density": spec_data.pixel_density_rows(catalog),
        "designs": spec_data.design_table_rows(catalog),
        "panels": spec_data.panel_table_rows(catalog),
        "battles": spec_data.battle_table_rows(catalog),
        "legend": spec_data.design_summary_by_kind(catalog),
        "svg_markup": render_spec_svg(catalog),
        "prose": prose,
        "cost": cost_ledger.summary(),
        "has_palette": fs_ws.has_palette(board_id),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict() if user else None,
    })
    return request.app.state.templates.TemplateResponse(request, "spec.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/frame", response_class=HTMLResponse)
def frame_view(request: Request, board_id: NestedBoardId):
    """House-frame picker / library page."""
    catalog = deps.load_board_catalog(board_id)

    with bf_config.set_active_board(board_id):
        has_frame = bf_frames.has_house_frame()
        meta = bf_frames.read_house_meta() if has_frame else None

    panels = catalog.get("feature_panels", {}).get("panels", [])
    store = bs.get_store()
    bp = _board_prefix(board_id)
    candidates = []
    for p in panels:
        live_rel = fs_ws.live_rel("panels", p["id"])
        if not store.exists(board_id, live_rel):
            continue
        url_rel = live_rel.removeprefix("workspace/")
        candidates.append({
            "id": p["id"],
            "size": [p["target_size"][0], p["target_size"][1]],
            "url": asset_urls.board_asset_url(
                http_prefix=bp,
                asset_relpath=url_rel,
                mtime_ms=store.stat(board_id, live_rel).mtime_ms,
            ),
        })

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "has_frame": has_frame,
        "meta": meta.to_dict() if meta else None,
        "candidates": candidates,
        "frame_enabled": bool((catalog.get("frame") or {}).get("enabled")),
        "frame_url": f"{bp}/frame.png?t={asset_urls.wall_clock_ms()}" if has_frame else None,
    })
    return request.app.state.templates.TemplateResponse(request, "frame.html", ctx)


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


@router.get("/users/{username}/board-games/{path_slug}/preview", response_class=HTMLResponse)
def preview_view(request: Request, board_id: NestedBoardId):
    store = bs.get_store()
    preview_rel = svc_boards.composite_preview_workspace_rel(board_id)
    preview_present = preview_rel is not None
    preview_url = None
    bp = _board_prefix(board_id)
    if preview_rel is not None:
        preview_url = asset_urls.board_asset_url(
            http_prefix=bp,
            asset_relpath=preview_rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, preview_rel).mtime_ms,
        )
    manifest_present = store.exists(board_id, "export/board_manifest.json")
    exported_count = sum(1 for f in store.list(board_id, "export") if f.endswith(".png"))
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "preview_present": preview_present,
        "preview_url": preview_url,
        "manifest_present": manifest_present,
        "exported_count": exported_count,
    })
    return request.app.state.templates.TemplateResponse(request, "preview.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/device-preview", response_class=HTMLResponse)
def device_preview_view(request: Request, board_id: NestedBoardId):
    """Composited board inside device frame mockups."""
    store = bs.get_store()
    bp = _board_prefix(board_id)

    def _asset_url(name: str) -> str | None:
        rel = f"workspace/preview/{name}"
        if not store.exists(board_id, rel):
            return None
        return asset_urls.board_asset_url(
            http_prefix=bp,
            asset_relpath=rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, rel).mtime_ms,
        )

    idle_url = _asset_url("board_idle.png")
    active_url = _asset_url("board_active.png")

    catalog = deps.load_board_catalog(board_id)
    bw, bh = catalog.get("board_size", [1920, 1080])

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "idle_url": idle_url,
        "active_url": active_url,
        "preview_present": bool(idle_url or active_url),
        "board_w": bw,
        "board_h": bh,
    })
    return request.app.state.templates.TemplateResponse(request, "device_preview.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/api/generation")
def api_get_generation(request: Request, board_id: NestedBoardId):
    """JSON for the generation settings modal (palette, provider, models)."""
    catalog = deps.load_board_catalog(board_id)
    settings = svc_catalog.read_generation(catalog)
    return JSONResponse({
        "settings": settings,
        "options": {"pixellab_models": list_pixellab_presets()},
    })


@router.get("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}")
def api_cell(request: Request, board_id: NestedBoardId, category: str, asset_id: str):
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


# ═══ POST / PUT: nested (canonical) + legacy /b/… ═══


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
    bp = _board_prefix(board_id)
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


@router.post("/b/{board_id}/actions/upload-mockup")
async def action_upload_mockup_legacy(
    request: Request, board_id: str, file: UploadFile = File(...),
):
    deps.ensure_owned_board(request, board_id)
    return await _action_upload_mockup(request, board_id, file)


async def _action_generate_mockup(request: Request, board_id: str) -> JSONResponse:
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required.")
    if len(prompt) > 4000:
        raise HTTPException(400, "Prompt is too long (max 4000 chars).")

    user = auth.current_user(request)
    openai_key = (user.openai_api_key if user else "") or os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(
            400,
            "No OpenAI API key found. Save one in Account → Connections → OpenAI / ChatGPT.",
        )

    catalog = deps.load_board_catalog(board_id)
    settings = svc_catalog.read_generation(catalog)
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
    bp = _board_prefix(board_id)
    return JSONResponse({
        "ok": True,
        "size": [1920, 1080],
        "warn_aspect": False,
        "redirect": f"{bp}/setup?mockup_ready=1",
    })


@router.post("/users/{username}/board-games/{path_slug}/actions/generate-mockup")
async def action_generate_mockup_nested(request: Request, board_id: NestedBoardId):
    return await _action_generate_mockup(request, board_id)


@router.post("/b/{board_id}/actions/generate-mockup")
async def action_generate_mockup_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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
        svc_catalog.save_catalog(board_id, data)

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


@router.post("/b/{board_id}/api/frame/adopt")
async def api_frame_adopt_legacy(
    request: Request, board_id: str,
    source_kind: str = Form(...),
    source_id: str = Form(...),
    ring_px: int = Form(...),
    enable_after: bool = Form(default=True),
):
    deps.ensure_owned_board(request, board_id)
    return await _api_frame_adopt(
        request, board_id, source_kind, source_id, ring_px, enable_after,
    )


async def _api_frame_disable(request: Request, board_id: str) -> JSONResponse:
    data = deps.load_board_catalog(board_id)
    data.setdefault("frame", {})
    data["frame"]["enabled"] = False
    svc_catalog.save_catalog(board_id, data)
    return JSONResponse({"ok": True})


@router.post("/users/{username}/board-games/{path_slug}/api/frame/disable")
async def api_frame_disable_nested(request: Request, board_id: NestedBoardId):
    return await _api_frame_disable(request, board_id)


@router.post("/b/{board_id}/api/frame/disable")
async def api_frame_disable_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    return await _api_frame_disable(request, board_id)


def _board_home_redirect(board_id: str) -> str:
    return f"{_board_prefix(board_id)}/"


def _board_preview_redirect(board_id: str) -> str:
    return f"{_board_prefix(board_id)}/preview"


async def _action_analyze(request: Request, board_id: str) -> JSONResponse | RedirectResponse:
    user = auth.current_user(request)
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


@router.post("/b/{board_id}/actions/analyze")
async def action_analyze_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/style")
async def action_style_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/generate-missing/all")
async def action_generate_missing_all_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/states")
async def action_states_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/preview")
async def action_preview_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/export")
async def action_export_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/regen/{category}/{asset_id}")
async def action_regen_one_legacy(
    request: Request, board_id: str, category: str, asset_id: str,
    prompt_override: str | None = Form(default=None),
):
    deps.ensure_owned_board(request, board_id)
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


@router.post("/b/{board_id}/actions/clean/{category}/{asset_id}")
async def action_clean_one_legacy(request: Request, board_id: str, category: str, asset_id: str):
    deps.ensure_owned_board(request, board_id)
    return await _action_clean_one(request, board_id, category, asset_id)


async def _api_put_generation(request: Request, board_id: str) -> JSONResponse:
    body = await request.json()
    try:
        new_block = svc_catalog.write_generation(board_id, body)
    except svc_catalog.GenerationValidationError as e:
        raise HTTPException(400, str(e)) from None
    return JSONResponse({"settings": new_block})


@router.put("/users/{username}/board-games/{path_slug}/api/generation")
async def api_put_generation_nested(request: Request, board_id: NestedBoardId):
    return await _api_put_generation(request, board_id)


@router.put("/b/{board_id}/api/generation")
async def api_put_generation_legacy(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    return await _api_put_generation(request, board_id)


async def _api_patch_cell(
    request: Request, board_id: str, category: str, asset_id: str,
) -> JSONResponse:
    if category != "spaces":
        raise HTTPException(400, "Only perimeter spaces support PATCH metadata.")
    body = await request.json()
    space_kind = body.get("space_kind")
    if space_kind not in ("standard", "event"):
        raise HTTPException(
            400,
            'JSON body must include "space_kind": "standard" or "event"',
        )
    data = deps.load_board_catalog(board_id)
    designs = data.get("board_spaces", {}).get("designs", [])
    entry = next((x for x in designs if x["id"] == asset_id), None)
    if entry is None:
        raise HTTPException(404, f"Unknown space design: {asset_id}")
    entry["space_kind"] = space_kind
    svc_catalog.save_catalog(board_id, data)
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.patch("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}")
async def api_patch_cell_nested(
    request: Request, board_id: NestedBoardId, category: str, asset_id: str,
):
    return await _api_patch_cell(request, board_id, category, asset_id)


@router.patch("/b/{board_id}/api/cell/{category}/{asset_id}")
async def api_patch_cell_legacy(request: Request, board_id: str, category: str, asset_id: str):
    deps.ensure_owned_board(request, board_id)
    return await _api_patch_cell(request, board_id, category, asset_id)


def _api_cell_promote(
    request: Request, board_id: str, category: str, asset_id: str, filename: str,
) -> JSONResponse:
    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets
        try:
            bf_assets.promote(category, asset_id, filename)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.post("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}/promote")
def api_cell_promote_nested(
    request: Request, board_id: NestedBoardId, category: str, asset_id: str,
    filename: str = Form(...),
):
    return _api_cell_promote(request, board_id, category, asset_id, filename)


@router.post("/b/{board_id}/api/cell/{category}/{asset_id}/promote")
def api_cell_promote_legacy(
    request: Request, board_id: str, category: str, asset_id: str,
    filename: str = Form(...),
):
    deps.ensure_owned_board(request, board_id)
    return _api_cell_promote(request, board_id, category, asset_id, filename)


def _api_rename_board(request: Request, board_id: str, project_name: str) -> JSONResponse:
    try:
        summary = svc_boards.rename_board(auth.require_user(request).id, board_id, project_name)
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


@router.post("/b/{board_id}/api/rename")
def api_rename_board_legacy(request: Request, board_id: str, project_name: str = Form(...)):
    deps.ensure_owned_board(request, board_id)
    return _api_rename_board(request, board_id, project_name)


# ═══ Legacy GET /b/… → 307 to canonical nested URL ═══


@router.get("/b/{board_id}/")
def legacy_get_board_root(request: Request, board_id: str):
    return deps.redirect_legacy_board_get(request, board_id, "")


@router.get("/b/{board_id}/{rest:path}")
def legacy_get_board_rest(request: Request, board_id: str, rest: str):
    return deps.redirect_legacy_board_get(request, board_id, rest)

"""Per-board HTTP routes: views, pipeline actions, cell + asset APIs."""

from __future__ import annotations

import base64
import io
import os
import time
from functools import partial

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from PIL import Image

import auth
import cost_ledger
import pipeline_adapters
import spec_data
from board_svg import render_board_svg, render_spec_svg
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from boardfactory.providers.pixel.pixellab import list_pixellab_presets

from routes import deps
from services import boards as svc_boards
from services import catalog as svc_catalog
from services import cells as svc_cells
from services import mockup_prompt as mockup_prompt_svc
from storage.fs import workspace as fs_ws

router = APIRouter()


@router.get("/b/{board_id}/", response_class=HTMLResponse)
def board_view(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    if not fs_ws.has_palette(board_id):
        return RedirectResponse(f"/b/{board_id}/setup", status_code=303)

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

    # The board shows N positions; each design id can fill multiple positions
    # (e.g. side_property occupies 7 squares with the same art). We bill per
    # design (one provider call), but the user sees positions. Surface both
    # so the action label reads in board-units while the cost line reads in
    # billing-units.
    designs_list = catalog.get("board_spaces", {}).get("designs", [])
    total_positions = sum(len(d.get("positions", [])) for d in designs_list)
    missing_positions = sum(
        len(d.get("positions", [])) for d in designs_list
        if d["id"] in missing_space_ids
    )
    generated_positions = total_positions - missing_positions

    per_space_cost = pipeline_adapters.estimate_generate_one("spaces")
    per_panel_cost = pipeline_adapters.estimate_generate_one("panels")
    all_generate_estimate = pipeline_adapters.estimate_generate_all(
        n_missing_designs, n_missing_panels
    )
    n_missing_all = n_missing_designs + n_missing_panels
    n_generated_all = generated_designs + (n_panels - n_missing_panels)

    frame_overlay_url = None
    frame_block = catalog.get("frame", {}) or {}
    if frame_block.get("enabled") and frame_block.get("apply_to_panels", True):
        with bf_config.scope_board(board_id):
            if bf_frames.has_house_frame():
                frame_overlay_url = f"/b/{board_id}/frame.png"

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
                else "Generate missing spaces & UI"
            ),
        },
        "generation": svc_catalog.read_generation(catalog),
    })
    return request.app.state.templates.TemplateResponse(request, "board.html", ctx)


@router.get("/b/{board_id}/setup", response_class=HTMLResponse)
def setup_view(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    mockup_present, mockup_rel = svc_boards.mockup_present(board_id)
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "mockup_present": mockup_present,
        "mockup_rel": mockup_rel,
        "mockup_ready_hint": request.query_params.get("mockup_ready") == "1",
    })
    return request.app.state.templates.TemplateResponse(request, "setup.html", ctx)


@router.post("/b/{board_id}/actions/upload-mockup")
async def action_upload_mockup(
    request: Request,
    board_id: str,
    file: UploadFile = File(...),
):
    """Accept a PNG/JPEG mockup upload and save it as boards/<id>/mockup/board.png.

    Validates that the file is an image and checks the aspect ratio — a 16:9
    image (within 5% tolerance) is ideal but we accept anything and warn
    the user in the JSON response if it strays too far.
    """
    deps.ensure_owned_board(request, board_id)

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

    mockup_dir = fs_ws.board_root(board_id) / "mockup"
    mockup_dir.mkdir(parents=True, exist_ok=True)
    dest = mockup_dir / "board.png"

    img.convert("RGB").save(dest, format="PNG")

    return JSONResponse({
        "ok": True,
        "size": [w, h],
        "warn_aspect": warn,
        "redirect": f"/b/{board_id}/setup?mockup_ready=1",
    })


@router.post("/b/{board_id}/actions/generate-mockup")
async def action_generate_mockup(request: Request, board_id: str):
    """AI-generate a 1920×1080 mockup from a text prompt and save it.

    The composed prompt includes **derived layout context** from the board catalog
    (board size, perimeter-space counts, feature-panel count, centerpiece intent)
    plus an optional **style.prompt** snippet — see ``services.mockup_prompt``.

    Synchronous (blocks until done) to keep the setup flow simple. We ask
    OpenAI's Images API for the largest landscape size it supports
    (1536×1024 ≈ 3:2), centre-crop to 16:9, and resize to 1920×1080 so the
    result drops cleanly into the canvas-aware downstream pipeline.

    Key resolution: user.openai_api_key → OPENAI_API_KEY env var.
    """
    deps.ensure_owned_board(request, board_id)
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
        " — top-down board game canvas, 16:9 layout, decorative border with "
        "a clear central focal area, ornate framing for surrounding cells, "
        "rich cohesive palette, no text or logos."
    )
    full_prompt = mockup_prompt_svc.compose_mockup_image_prompt(
        prompt, catalog, framing_suffix=framing_suffix
    )
    if len(full_prompt) > 10000:
        raise HTTPException(
            400,
            "Combined prompt is too long after adding layout hints; shorten your description.",
        )

    api_size = "1536x1024"  # widest landscape OpenAI Images currently supports
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

    # Centre-crop to 16:9 then resize to 1920×1080 so the rest of the
    # pipeline can treat it identically to an uploaded reference.
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

    mockup_dir = fs_ws.board_root(board_id) / "mockup"
    mockup_dir.mkdir(parents=True, exist_ok=True)
    dest = mockup_dir / "board.png"
    img.save(dest, format="PNG")

    return JSONResponse({
        "ok": True,
        "size": [1920, 1080],
        "warn_aspect": False,
        "redirect": f"/b/{board_id}/setup?mockup_ready=1",
    })


@router.get("/b/{board_id}/spec", response_class=HTMLResponse)
def spec_view(request: Request, board_id: str):
    """Live tech spec from the board's catalog + the shared prose markdown."""
    deps.ensure_owned_board(request, board_id)
    catalog = deps.load_board_catalog(board_id)
    prose = deps.load_spec_prose_sections()
    user = getattr(request.state, "user", None)
    ctx = {
        "board_id": board_id,
        "project": catalog.get("project", board_id),
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
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
        "user": user.public_dict() if user else None,
    }
    return request.app.state.templates.TemplateResponse(request, "spec.html", ctx)


@router.get("/b/{board_id}/frame", response_class=HTMLResponse)
def frame_view(request: Request, board_id: str):
    """House-frame picker / library page."""
    deps.ensure_owned_board(request, board_id)
    catalog = deps.load_board_catalog(board_id)

    with bf_config.scope_board(board_id):
        has_frame = bf_frames.has_house_frame()
        meta = bf_frames.read_house_meta() if has_frame else None

    panels = catalog.get("feature_panels", {}).get("panels", [])
    candidates = []
    for p in panels:
        live = fs_ws.live_path(board_id, "panels", p["id"])
        if live.exists():
            candidates.append({
                "id": p["id"],
                "size": [p["target_size"][0], p["target_size"][1]],
                "url": f"/b/{board_id}/asset/{live.relative_to(fs_ws.workspace_dir(board_id)).as_posix()}?t={int(live.stat().st_mtime)}",
            })

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "has_frame": has_frame,
        "meta": meta.to_dict() if meta else None,
        "candidates": candidates,
        "frame_enabled": bool((catalog.get("frame") or {}).get("enabled")),
        "frame_url": f"/b/{board_id}/frame.png?t={int(time.time())}" if has_frame else None,
    })
    return request.app.state.templates.TemplateResponse(request, "frame.html", ctx)


@router.get("/b/{board_id}/frame.png")
def frame_overlay(request: Request, board_id: str, w: int = 0, h: int = 0):
    """Compose the house frame at the requested size on demand. Cacheable."""
    deps.ensure_owned_board(request, board_id)
    with bf_config.scope_board(board_id):
        loaded = bf_frames.load_house_frame()
    if loaded is None:
        raise HTTPException(404, "No house frame adopted on this board")

    slice_, meta = loaded
    if w <= 0 or h <= 0:
        # Return the raw composed-at-source-size frame for previews.
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


@router.post("/b/{board_id}/api/frame/adopt")
async def api_frame_adopt(
    request: Request, board_id: str,
    source_kind: str = Form(...),
    source_id: str = Form(...),
    ring_px: int = Form(...),
    enable_after: bool = Form(default=True),
):
    """Adopt a 9-slice extracted from an existing panel asset as the house frame.

    source_kind: 'panel'  → source_id = panel id, reads workspace/live/panels/<id>.png
                 'mockup' → source_id = panel id whose bbox slice of the mockup is used
    """
    deps.ensure_owned_board(request, board_id)
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
        # Resize to the panel's target_size so ring_px is in target-asset pixels.
        tw, th = p["target_size"]
        src_img = src_img.resize((tw, th), Image.NEAREST)
        src_size = (tw, th)
    else:
        raise HTTPException(400, f"Unknown source_kind {source_kind!r}")

    # Validate ring fits.
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
        # Flip the frame.enabled bit on so the compositor / SVG honor the new frame.
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


@router.post("/b/{board_id}/api/frame/disable")
async def api_frame_disable(request: Request, board_id: str):
    """Turn off frame overlay without deleting the frame assets."""
    deps.ensure_owned_board(request, board_id)
    data = deps.load_board_catalog(board_id)
    data.setdefault("frame", {})
    data["frame"]["enabled"] = False
    svc_catalog.save_catalog(board_id, data)
    return JSONResponse({"ok": True})


@router.get("/b/{board_id}/api/frame/preview.png")
def api_frame_preview(request: Request, board_id: str, source_kind: str, source_id: str,
                      ring_px: int, w: int = 260, h: int = 240):
    """Live preview: extract 9-slice + recompose at target size, no disk write.

    Used by the picker UI's thickness slider for instant feedback.
    """
    deps.ensure_owned_board(request, board_id)
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


@router.get("/b/{board_id}/preview", response_class=HTMLResponse)
def preview_view(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    preview_path = fs_ws.workspace_dir(board_id) / "preview" / "board_preview.png"
    export_dir = fs_ws.export_dir(board_id)
    manifest_path = export_dir / "board_manifest.json"
    exported_count = 0
    if export_dir.exists():
        exported_count = sum(1 for _ in export_dir.rglob("*.png"))
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "preview_present": preview_path.exists(),
        "preview_url": (
            f"/b/{board_id}/asset/preview/board_preview.png?t={int(preview_path.stat().st_mtime)}"
            if preview_path.exists() else None
        ),
        "manifest_present": manifest_path.exists(),
        "exported_count": exported_count,
    })
    return request.app.state.templates.TemplateResponse(request, "preview.html", ctx)


@router.get("/b/{board_id}/device-preview", response_class=HTMLResponse)
def device_preview_view(request: Request, board_id: str):
    """Show the composited board inside renderings of physical screens.

    Renders the same workspace/preview/board_*.png the compositor produces
    inside CSS mockups of TV / desktop / laptop / Switch / Steam Deck so
    the board can be sanity-checked at multiple form factors without
    leaving the browser.
    """
    deps.ensure_owned_board(request, board_id)
    preview_dir = fs_ws.workspace_dir(board_id) / "preview"
    idle_path = preview_dir / "board_idle.png"
    active_path = preview_dir / "board_active.png"

    def _asset_url(name: str, p: Path) -> str:
        return f"/b/{board_id}/asset/preview/{name}?t={int(p.stat().st_mtime)}"

    idle_url = _asset_url("board_idle.png", idle_path) if idle_path.exists() else None
    active_url = _asset_url("board_active.png", active_path) if active_path.exists() else None

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


# ────────────────────────── routes: pipeline actions (board-scoped) ──────────────────────────


@router.post("/b/{board_id}/actions/analyze")
async def action_analyze(request: Request, board_id: str):
    """Send the board mockup to GPT-4o vision and auto-fill every catalog prompt.

    Key resolution (first found wins):
      1. The requesting user's saved openai_api_key
      2. OPENAI_API_KEY environment variable
    If neither is set, returns 400 so the UI can surface a clear message.
    """
    deps.ensure_owned_board(request, board_id)

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
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/")


@router.post("/b/{board_id}/actions/style")
async def action_style(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    job_id = deps.enqueue_pipeline_job(
        label="Extract style from mockup",
        operation="style", target=board_id,
        cost_estimate=pipeline_adapters.estimate_style(),
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.style),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/")


@router.post("/b/{board_id}/actions/generate-missing/all")
async def action_generate_missing_all(request: Request, board_id: str):
    """Generate every empty board space AND every empty UI panel in one job."""
    deps.ensure_owned_board(request, board_id)
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
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/")


@router.post("/b/{board_id}/actions/states")
async def action_states(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    job_id = deps.enqueue_pipeline_job(
        label="Build active states",
        operation="states", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.states),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@router.post("/b/{board_id}/actions/preview")
async def action_preview(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    job_id = deps.enqueue_pipeline_job(
        label="Composite preview",
        operation="preview", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.preview),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@router.post("/b/{board_id}/actions/export")
async def action_export(request: Request, board_id: str):
    deps.ensure_owned_board(request, board_id)
    job_id = deps.enqueue_pipeline_job(
        label="Export approved assets",
        operation="export", target=board_id,
        cost_estimate=0.0,
        fn=deps.scoped_pipeline_callable(board_id, pipeline_adapters.export),
    )
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@router.post("/b/{board_id}/actions/regen/{category}/{asset_id}")
async def action_regen_one(
    request: Request, board_id: str, category: str, asset_id: str,
    prompt_override: str | None = Form(default=None),
):
    """Regenerate exactly one cell with optional prompt override."""
    deps.ensure_owned_board(request, board_id)
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
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/")


@router.post("/b/{board_id}/actions/clean/{category}/{asset_id}")
async def action_clean_one(request: Request, board_id: str, category: str, asset_id: str):
    """Re-clean the current live image for one cell. Free, fast."""
    deps.ensure_owned_board(request, board_id)
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
    return deps.job_or_redirect_response(request, job_id, redirect_to=f"/b/{board_id}/")


@router.get("/b/{board_id}/api/generation")
def api_get_generation(request: Request, board_id: str):
    """JSON for the generation settings modal (palette, provider, models)."""
    deps.ensure_owned_board(request, board_id)
    catalog = deps.load_board_catalog(board_id)
    settings = svc_catalog.read_generation(catalog)
    return JSONResponse({
        "settings": settings,
        "options": {"pixellab_models": list_pixellab_presets()},
    })


@router.put("/b/{board_id}/api/generation")
async def api_put_generation(request: Request, board_id: str):
    """Persist generation block; marks the board as configured for the UI."""
    deps.ensure_owned_board(request, board_id)
    body = await request.json()
    try:
        new_block = svc_catalog.write_generation(board_id, body)
    except svc_catalog.GenerationValidationError as e:
        raise HTTPException(400, str(e)) from None
    return JSONResponse({"settings": new_block})


@router.get("/b/{board_id}/api/cell/{category}/{asset_id}")
def api_cell(request: Request, board_id: str, category: str, asset_id: str):
    deps.ensure_owned_board(request, board_id)
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.post("/b/{board_id}/api/cell/{category}/{asset_id}/promote")
def api_cell_promote(request: Request, board_id: str, category: str, asset_id: str,
                     filename: str = Form(...)):
    deps.ensure_owned_board(request, board_id)
    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets
        try:
            bf_assets.promote(category, asset_id, filename)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.post("/b/{board_id}/api/rename")
def api_rename_board(request: Request, board_id: str, project_name: str = Form(...)):
    """Persist display title to relational catalog (slug / URL unchanged)."""
    deps.ensure_owned_board(request, board_id)
    try:
        summary = svc_boards.rename_board(auth.require_user(request).id, board_id, project_name)
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Board not found") from None
    except svc_boards.InvalidBoardId as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return JSONResponse({"ok": True, "project": summary.project})


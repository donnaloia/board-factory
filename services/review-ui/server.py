"""Board Factory review UI — multi-board operating room.

Boards live at boards/<id>/ on disk, each with its own catalog, workspace,
mockup, and exports. URLs are scoped: /b/<board_id>/... for everything
board-specific. The root / is a board picker.

All long-running pipeline steps run as background Jobs. The browser
subscribes to /events/jobs (SSE) for live progress, log, and cost.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

import markdown as md

from board_svg import CellStatus, render_board_svg, render_spec_svg
import spec_data
import cost_ledger
import pipeline_adapters
from jobs import get_runner

# Pipeline imports — these access config.PATH attributes lazily, so we just
# need to make sure config.set_board(...) is called before any of them run.
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
SPEC_PROSE_PATH = REPO_ROOT / "docs" / "spec_prose.md"
BOARDS_DIR = REPO_ROOT / "boards"

app = FastAPI(title="Board Factory Review")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ────────────────────────── one-time bootstrap ──────────────────────────


@app.on_event("startup")
def startup() -> None:
    """Migrate the legacy flat layout into boards/damnation/ on first boot."""
    bf_boards.migrate_legacy_flat_layout(target_board_id="damnation")


# ────────────────────────── per-board path helpers ──────────────────────────


def _board_root(board_id: str) -> Path:
    return BOARDS_DIR / board_id


def _catalog_path(board_id: str) -> Path:
    return _board_root(board_id) / "catalog.yml"


def _workspace(board_id: str) -> Path:
    return _board_root(board_id) / "workspace"


def _approved_path(board_id: str, category: str, asset_id: str) -> Path:
    if category == "centerpiece":
        return _workspace(board_id) / "approved" / "centerpiece.png"
    return _workspace(board_id) / "approved" / category / f"{asset_id}.png"


def _live_path(board_id: str, category: str, asset_id: str) -> Path:
    if category == "centerpiece":
        return _workspace(board_id) / "live" / "centerpiece" / "centerpiece.png"
    return _workspace(board_id) / "live" / category / f"{asset_id}.png"


def _history_dir(board_id: str, category: str, asset_id: str) -> Path:
    return _workspace(board_id) / "history" / category / asset_id


def _candidates(board_id: str, category: str, asset_id: str | None = None) -> list[Path]:
    base = _workspace(board_id) / "cleaned" / category
    if asset_id:
        base = base / asset_id
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.png") if not p.name.startswith("_"))


def _safe_workspace_path(board_id: str, rel: str) -> Path:
    """Resolve a workspace-relative path safely (no traversal outside workspace)."""
    ws = _workspace(board_id)
    target = (ws / rel).resolve()
    if not str(target).startswith(str(ws.resolve())):
        raise HTTPException(400, "Invalid path")
    return target


def _palette_for_provider(board_id: str) -> list[tuple[int, int, int]] | None:
    pal_path = _workspace(board_id) / "style" / "palette.json"
    if not pal_path.exists():
        return None
    return [tuple(c) for c in json.loads(pal_path.read_text())]


def _has_palette(board_id: str) -> bool:
    return (_workspace(board_id) / "style" / "palette.json").exists()


def _mockup_present(board_id: str) -> tuple[bool, str]:
    """Return (exists, board-relative path string used in templates)."""
    cat_path = _catalog_path(board_id)
    rel = "mockup/board.png"
    if cat_path.exists():
        try:
            with cat_path.open() as f:
                data = yaml.safe_load(f) or {}
            rel = (data.get("style") or {}).get("reference_image", rel)
        except Exception:
            pass
    return ((_board_root(board_id) / rel).exists(), rel)


def _load_catalog(board_id: str) -> dict:
    p = _catalog_path(board_id)
    if not p.exists():
        raise HTTPException(404, f"Catalog not found for board {board_id!r}")
    with p.open() as f:
        return yaml.safe_load(f)


def _ensure_board_or_404(board_id: str) -> bf_boards.BoardInfo:
    if not bf_boards.is_valid_id(board_id):
        raise HTTPException(400, "Invalid board id")
    info = bf_boards.get_board(board_id)
    if info is None:
        raise HTTPException(404, f"Unknown board {board_id!r}")
    return info


def _seed_history_if_needed(board_id: str, category: str, asset_id: str) -> None:
    """If a legacy approved/<asset_id>.png exists but no live/, seed both."""
    if _live_path(board_id, category, asset_id).exists():
        return
    legacy = _approved_path(board_id, category, asset_id)
    if not legacy.exists():
        return
    with bf_config.scope_board(board_id):
        try:
            from boardfactory import assets as bf_assets
            bf_assets.seed_from_legacy_approved(category, asset_id)
        except Exception:
            pass


def _cell_status(board_id: str, category: str, asset_id: str) -> CellStatus:
    _seed_history_if_needed(board_id, category, asset_id)
    live = _live_path(board_id, category, asset_id)
    is_live = live.exists()

    history_count = 0
    hd = _history_dir(board_id, category, asset_id)
    if hd.exists():
        history_count = sum(1 for _ in hd.glob("*.png"))
    if history_count == 0:
        history_count = len(_candidates(board_id, category,
                                        asset_id if category != "centerpiece" else None))

    live_url = None
    if is_live:
        rel = live.relative_to(_workspace(board_id))
        live_url = f"/b/{board_id}/asset/{rel.as_posix()}"

    return CellStatus(
        asset_id=asset_id,
        category=category,
        candidates=history_count,
        approved=is_live,
        approved_url=live_url,
    )


# ────────────────────────── template context helpers ──────────────────────────


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept


def _action_response(request: Request, job_id: str, redirect_to: str = "/") -> JSONResponse | RedirectResponse:
    if _wants_json(request):
        return JSONResponse({"job_id": job_id})
    return RedirectResponse(redirect_to, status_code=303)


def _base_context(board_id: str | None) -> dict:
    """Common context for every editorial template — the cost meter is global,
    everything else scopes to the board if there is one."""
    project = "Board Factory"
    if board_id:
        info = bf_boards.get_board(board_id)
        if info:
            project = info.project
    return {
        "board_id": board_id,
        "project": project,
        "has_palette": _has_palette(board_id) if board_id else False,
        "cost": cost_ledger.summary(),
        "estimates": _estimates() if board_id else
                     {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
    }


def _estimates() -> dict:
    return {
        "spaces": pipeline_adapters.estimate_generate("spaces"),
        "panels": pipeline_adapters.estimate_generate("panels"),
        "centerpiece": pipeline_adapters.estimate_generate("centerpiece"),
        "refine": pipeline_adapters.estimate_refine(),
    }


def _enqueue(*, label: str, operation: str, target: str | None,
             cost_estimate: float, fn) -> str:
    runner = get_runner()
    job = runner.enqueue(
        label=label, operation=operation, target=target,
        cost_estimate=cost_estimate, fn=fn,
    )
    return job.id


def _scoped_fn(board_id: str, fn):
    """Wrap a job worker fn so it runs inside config.scope_board(board_id)."""
    def wrapped(job, cancel):
        with bf_config.scope_board(board_id):
            return fn(job, cancel)
    return wrapped


def _load_spec_prose() -> dict[str, str]:
    if not SPEC_PROSE_PATH.exists():
        return {}
    raw = SPEC_PROSE_PATH.read_text()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is None:
            continue
        sections[current].append(line)
    return {
        slug: md.markdown("\n".join(body), extensions=["tables"])
        for slug, body in sections.items()
    }


# ────────────────────────── routes: board picker + mgmt ──────────────────────────


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    """Board picker. If only one board exists, jump straight to it."""
    boards = bf_boards.list_boards()
    if not boards:
        # First-time install with no migration to perform — drop into a "no
        # boards yet" state so the user can create one.
        ctx = _base_context(None)
        ctx.update({"boards": [], "has_any_board": False})
        return templates.TemplateResponse(request, "boards_index.html", ctx)

    if len(boards) == 1:
        return RedirectResponse(f"/b/{boards[0].id}/", status_code=303)

    ctx = _base_context(None)
    ctx.update({"boards": boards, "has_any_board": True})
    return templates.TemplateResponse(request, "boards_index.html", ctx)


@app.post("/api/boards")
async def api_create_board(request: Request, board_id: str = Form(...),
                           project_name: str | None = Form(default=None)):
    """Create a new empty board, return its id + URL."""
    bid = bf_boards.slugify(board_id)
    if bf_boards.get_board(bid) is not None:
        raise HTTPException(409, f"Board {bid!r} already exists")
    info = bf_boards.create_board(bid, project_name=project_name or board_id)
    return JSONResponse({"id": info.id, "url": f"/b/{info.id}/"})


@app.post("/b/{board_id}/api/rename")
def api_rename_board(board_id: str, project_name: str = Form(...)):
    """Rename a board's display name. Returns the updated board info."""
    _ensure_board_or_404(board_id)
    try:
        info = bf_boards.rename_board_project(board_id, project_name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"id": info.id, "project": info.project})


# ────────────────────────── routes: per-board views ──────────────────────────


@app.get("/b/{board_id}/", response_class=HTMLResponse)
def board_view(request: Request, board_id: str):
    info = _ensure_board_or_404(board_id)
    if not _has_palette(board_id):
        return RedirectResponse(f"/b/{board_id}/setup", status_code=303)

    catalog = _load_catalog(board_id)
    space_status = {
        d["id"]: _cell_status(board_id, "spaces", d["id"])
        for d in catalog.get("board_spaces", {}).get("designs", [])
    }
    panel_status = {
        p["id"]: _cell_status(board_id, "panels", p["id"])
        for p in catalog.get("feature_panels", {}).get("panels", [])
    }
    cp_status = _cell_status(board_id, "centerpiece", "centerpiece")

    n_designs = len(space_status)
    n_panels = len(panel_status)
    designs_done = sum(1 for s in space_status.values() if s.approved)
    panels_done = sum(1 for s in panel_status.values() if s.approved)

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

    ctx = _base_context(board_id)
    ctx.update({
        "board_size": catalog["board_size"],
        "svg_markup": svg_markup,
        "stats": {
            "designs_total": n_designs,
            "designs_done": designs_done,
            "panels_total": n_panels,
            "panels_done": panels_done,
            "centerpiece_done": cp_status.approved,
        },
    })
    return templates.TemplateResponse(request, "board.html", ctx)


@app.get("/b/{board_id}/setup", response_class=HTMLResponse)
def setup_view(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    mockup_present, mockup_rel = _mockup_present(board_id)
    ctx = _base_context(board_id)
    ctx.update({"mockup_present": mockup_present, "mockup_rel": mockup_rel})
    return templates.TemplateResponse(request, "setup.html", ctx)


@app.get("/b/{board_id}/spec", response_class=HTMLResponse)
def spec_view(request: Request, board_id: str):
    """Live tech spec from the board's catalog + the shared prose markdown."""
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)
    prose = _load_spec_prose()
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
        "has_palette": _has_palette(board_id),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
    }
    return templates.TemplateResponse(request, "spec.html", ctx)


@app.get("/b/{board_id}/frame", response_class=HTMLResponse)
def frame_view(request: Request, board_id: str):
    """House-frame picker / library page."""
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)

    with bf_config.scope_board(board_id):
        has_frame = bf_frames.has_house_frame()
        meta = bf_frames.read_house_meta() if has_frame else None

    panels = catalog.get("feature_panels", {}).get("panels", [])
    candidates = []
    for p in panels:
        live = _live_path(board_id, "panels", p["id"])
        if live.exists():
            candidates.append({
                "id": p["id"],
                "size": [p["target_size"][0], p["target_size"][1]],
                "url": f"/b/{board_id}/asset/{live.relative_to(_workspace(board_id)).as_posix()}?t={int(live.stat().st_mtime)}",
            })

    ctx = _base_context(board_id)
    ctx.update({
        "has_frame": has_frame,
        "meta": meta.to_dict() if meta else None,
        "candidates": candidates,
        "frame_enabled": bool((catalog.get("frame") or {}).get("enabled")),
        "frame_url": f"/b/{board_id}/frame.png?t={int(time.time())}" if has_frame else None,
    })
    return templates.TemplateResponse(request, "frame.html", ctx)


@app.get("/b/{board_id}/frame.png")
def frame_overlay(board_id: str, w: int = 0, h: int = 0):
    """Compose the house frame at the requested size on demand. Cacheable."""
    _ensure_board_or_404(board_id)
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


@app.post("/b/{board_id}/api/frame/adopt")
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
    _ensure_board_or_404(board_id)
    if ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    catalog = _load_catalog(board_id)
    src_img: Image.Image
    src_size: tuple[int, int]

    if source_kind == "panel":
        live = _live_path(board_id, "panels", source_id)
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
        mockup_path = _board_root(board_id) / ref_rel
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
        cat_path = _catalog_path(board_id)
        with cat_path.open() as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("frame", {})
        data["frame"]["enabled"] = True
        data["frame"]["apply_to_panels"] = True
        cat_path.write_text(yaml.safe_dump(data, sort_keys=False))

    return JSONResponse({
        "ok": True,
        "ring_px": ring_px,
        "source_kind": source_kind,
        "source_id": source_id,
    })


@app.post("/b/{board_id}/api/frame/disable")
async def api_frame_disable(request: Request, board_id: str):
    """Turn off frame overlay without deleting the frame assets."""
    _ensure_board_or_404(board_id)
    cat_path = _catalog_path(board_id)
    with cat_path.open() as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("frame", {})
    data["frame"]["enabled"] = False
    cat_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return JSONResponse({"ok": True})


@app.get("/b/{board_id}/api/frame/preview.png")
def api_frame_preview(board_id: str, source_kind: str, source_id: str,
                      ring_px: int, w: int = 260, h: int = 240):
    """Live preview: extract 9-slice + recompose at target size, no disk write.

    Used by the picker UI's thickness slider for instant feedback.
    """
    _ensure_board_or_404(board_id)
    if ring_px < 2:
        raise HTTPException(400, "ring_px must be at least 2")

    catalog = _load_catalog(board_id)
    if source_kind == "panel":
        live = _live_path(board_id, "panels", source_id)
        if not live.exists():
            raise HTTPException(404)
        src_img = Image.open(live).convert("RGBA")
    elif source_kind == "mockup":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == source_id), None)
        if p is None:
            raise HTTPException(404)
        mockup_path = _board_root(board_id) / catalog["style"]["reference_image"]
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


@app.get("/b/{board_id}/preview", response_class=HTMLResponse)
def preview_view(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    preview_path = _workspace(board_id) / "preview" / "board_preview.png"
    manifest_path = _board_root(board_id) / "board_assets" / "manifest.json"
    exported_count = 0
    export_dir = _board_root(board_id) / "board_assets"
    if export_dir.exists():
        exported_count = sum(1 for _ in export_dir.rglob("*.png"))
    ctx = _base_context(board_id)
    ctx.update({
        "preview_present": preview_path.exists(),
        "preview_url": (
            f"/b/{board_id}/asset/preview/board_preview.png?t={int(preview_path.stat().st_mtime)}"
            if preview_path.exists() else None
        ),
        "manifest_present": manifest_path.exists(),
        "exported_count": exported_count,
    })
    return templates.TemplateResponse(request, "preview.html", ctx)


# Legacy routes — redirect to the per-board equivalent if there's a default board.

@app.get("/spec")
def legacy_spec():
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/spec" if bid else "/", status_code=301)


@app.get("/preview")
def legacy_preview():
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/preview" if bid else "/", status_code=301)


@app.get("/setup")
def legacy_setup():
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/setup" if bid else "/", status_code=301)


@app.get("/spaces")
def legacy_spaces():
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/" if bid else "/", status_code=301)


@app.get("/panels/{panel_id}")
def legacy_panel(panel_id: str):
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/#panels:{panel_id}" if bid else "/", status_code=301)


@app.get("/centerpiece")
def legacy_centerpiece():
    bid = bf_boards.default_board_id()
    return RedirectResponse(f"/b/{bid}/#centerpiece:centerpiece" if bid else "/",
                            status_code=301)


# ────────────────────────── routes: pipeline actions (board-scoped) ──────────────────────────


@app.post("/b/{board_id}/actions/style")
async def action_style(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    job_id = _enqueue(
        label="Extract style from mockup",
        operation="style", target=board_id,
        cost_estimate=pipeline_adapters.estimate_style(),
        fn=_scoped_fn(board_id, pipeline_adapters.style_adapter()),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/generate/{category}")
async def action_generate(request: Request, board_id: str, category: str):
    _ensure_board_or_404(board_id)
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    job_id = _enqueue(
        label=f"Generate {category}",
        operation=f"generate.{category}", target=board_id,
        cost_estimate=pipeline_adapters.estimate_generate(category),
        fn=_scoped_fn(board_id, pipeline_adapters.generate_adapter(category)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/cleanup")
async def action_cleanup(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    job_id = _enqueue(
        label="Pixel cleanup",
        operation="cleanup", target=board_id,
        cost_estimate=0.0,
        fn=_scoped_fn(board_id, pipeline_adapters.cleanup_adapter()),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/states")
async def action_states(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    job_id = _enqueue(
        label="Build active states",
        operation="states", target=board_id,
        cost_estimate=0.0,
        fn=_scoped_fn(board_id, pipeline_adapters.states_adapter()),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@app.post("/b/{board_id}/actions/preview")
async def action_preview(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    job_id = _enqueue(
        label="Composite preview",
        operation="preview", target=board_id,
        cost_estimate=0.0,
        fn=_scoped_fn(board_id, pipeline_adapters.preview_adapter()),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@app.post("/b/{board_id}/actions/export")
async def action_export(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    job_id = _enqueue(
        label="Export approved assets",
        operation="export", target=board_id,
        cost_estimate=0.0,
        fn=_scoped_fn(board_id, pipeline_adapters.export_adapter()),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/preview")


@app.post("/b/{board_id}/actions/regen/{category}/{asset_id}")
async def action_regen_one(
    request: Request, board_id: str, category: str, asset_id: str,
    prompt_override: str | None = Form(default=None),
):
    """Regenerate exactly one cell with optional prompt override."""
    _ensure_board_or_404(board_id)
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    p = (prompt_override or "").strip() or None
    job_id = _enqueue(
        label=f"Regenerate {asset_id}",
        operation=f"regen.{category}", target=asset_id,
        cost_estimate=pipeline_adapters.estimate_regen_one(category, asset_id),
        fn=_scoped_fn(board_id,
                      pipeline_adapters.regen_one_adapter(category, asset_id,
                                                          prompt_override=p)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/clean/{category}/{asset_id}")
async def action_clean_one(request: Request, board_id: str, category: str, asset_id: str):
    """Re-clean the current live image for one cell. Free, fast."""
    _ensure_board_or_404(board_id)
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    job_id = _enqueue(
        label=f"Clean {asset_id}",
        operation=f"clean.{category}", target=asset_id,
        cost_estimate=0.0,
        fn=_scoped_fn(board_id,
                      pipeline_adapters.clean_one_adapter(category, asset_id)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


# ────────────────────────── routes: cell state (side panel) ──────────────────────────


def _cell_payload(board_id: str, category: str, asset_id: str) -> dict:
    """JSON state for one cell: spec + live url + history list (with prompts)."""
    _seed_history_if_needed(board_id, category, asset_id)
    catalog = _load_catalog(board_id)

    spec: dict = {}
    if category == "spaces":
        designs = catalog.get("board_spaces", {}).get("designs", [])
        d = next((x for x in designs if x["id"] == asset_id), None)
        if d is None:
            raise HTTPException(404, f"Unknown space design: {asset_id}")
        from board_svg import _resolve_position
        layout = catalog["board_spaces"]["layout"]
        sample_pos = d["positions"][0] if d.get("positions") else None
        size = None
        if sample_pos:
            x, y, w, h = _resolve_position(layout, sample_pos)
            size = [w, h]
        spec = {
            "id": d["id"], "title": d["id"].replace("_", " "),
            "prompt": d.get("prompt", ""),
            "uses": len(d.get("positions", [])),
            "size": size, "kind": "space",
        }
    elif category == "panels":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == asset_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel: {asset_id}")
        spec = {
            "id": p["id"], "title": p["id"].replace("_", " "),
            "prompt": p.get("prompt", ""), "uses": 1,
            "size": list(p["target_size"]), "kind": "panel",
        }
    elif category == "centerpiece":
        cp = catalog["centerpiece"]
        spec = {
            "id": "centerpiece", "title": "Centerpiece",
            "prompt": cp.get("prompt", ""), "uses": 1,
            "size": list(cp["target_size"]), "kind": "centerpiece",
        }
    else:
        raise HTTPException(400, f"Unknown category {category}")

    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets
        entries = bf_assets.list_history(category, asset_id)

    history = [
        {
            "filename": e.filename, "ts_ms": e.timestamp_ms, "seq": e.seq,
            "is_live": e.is_live, "operation": e.operation, "prompt": e.prompt,
            "url": f"/b/{board_id}/asset/history/{category}/{asset_id}/{e.filename}",
        }
        for e in entries
    ]

    live = _live_path(board_id, category, asset_id)
    live_url = None
    if live.exists():
        live_url = f"/b/{board_id}/asset/{live.relative_to(_workspace(board_id)).as_posix()}?t={int(live.stat().st_mtime)}"

    catalog_prompt = spec.get("prompt", "") or ""
    active_prompt = catalog_prompt
    for e in entries:
        if e.is_live and e.prompt is not None:
            active_prompt = e.prompt
            break

    # Frame info — only relevant for panels right now.
    frame_block = catalog.get("frame", {}) or {}
    frame_enabled_for_cell = (
        category == "panels"
        and bool(frame_block.get("enabled"))
        and bool(frame_block.get("apply_to_panels", True))
    )
    with bf_config.scope_board(board_id):
        frame_present = bf_frames.has_house_frame()
    frame_locked = frame_enabled_for_cell and frame_present and live.exists()

    return {
        "board_id": board_id,
        "category": category, "asset_id": asset_id,
        "spec": spec,
        "live_url": live_url, "has_live": live.exists(),
        "history": history,
        "catalog_prompt": catalog_prompt, "active_prompt": active_prompt,
        "regen_estimate_usd": pipeline_adapters.estimate_regen_one(category, asset_id),
        "candidates_per_regen": _candidates_per_regen(category),
        "frame_locked": frame_locked,
        "frame_url": f"/b/{board_id}/frame.png?w={spec['size'][0]}&h={spec['size'][1]}" if frame_locked and spec.get("size") else None,
    }


def _candidates_per_regen(category: str) -> int:
    if category == "spaces":
        return bf_config.SPACE_CANDIDATES
    if category == "panels":
        return bf_config.PANEL_CANDIDATES
    if category == "centerpiece":
        return bf_config.CENTERPIECE_CANDIDATES
    return 0


@app.get("/b/{board_id}/api/cell/{category}/{asset_id}")
def api_cell(board_id: str, category: str, asset_id: str):
    _ensure_board_or_404(board_id)
    return JSONResponse(_cell_payload(board_id, category, asset_id))


@app.post("/b/{board_id}/api/cell/{category}/{asset_id}/promote")
def api_cell_promote(board_id: str, category: str, asset_id: str,
                     filename: str = Form(...)):
    _ensure_board_or_404(board_id)
    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets
        try:
            bf_assets.promote(category, asset_id, filename)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
    return JSONResponse(_cell_payload(board_id, category, asset_id))


# ────────────────────────── routes: jobs / SSE / cost ──────────────────────────


@app.get("/jobs")
def jobs_index():
    runner = get_runner()
    return JSONResponse({"jobs": [j.to_dict() for j in runner.all_jobs()]})


@app.get("/jobs/{job_id}")
def job_detail(job_id: str):
    runner = get_runner()
    j = runner.get(job_id)
    if not j:
        raise HTTPException(404, f"No such job {job_id}")
    return JSONResponse({**j.to_dict(), "log": list(j.log)})


@app.post("/jobs/{job_id}/kill")
def job_kill(job_id: str):
    runner = get_runner()
    if not runner.kill(job_id):
        raise HTTPException(404, f"No such job {job_id}")
    return JSONResponse({"ok": True})


@app.get("/events/jobs")
async def events_jobs(request: Request):
    runner = get_runner()

    async def stream():
        snapshot = {"jobs": [j.to_dict() for j in runner.all_jobs()]}
        yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
        q = runner.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: job\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            runner.unsubscribe(q)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


@app.get("/api/cost-summary")
def cost_summary():
    return JSONResponse(cost_ledger.summary())


# ────────────────────────── routes: assets ──────────────────────────


@app.get("/b/{board_id}/asset/{rest:path}")
def asset(board_id: str, rest: str):
    _ensure_board_or_404(board_id)
    target = _safe_workspace_path(board_id, rest)
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


@app.get("/b/{board_id}/mockup/{name}")
def mockup(board_id: str, name: str):
    _ensure_board_or_404(board_id)
    mockup_dir = (_board_root(board_id) / "mockup").resolve()
    target = (mockup_dir / name).resolve()
    if not str(target).startswith(str(mockup_dir)):
        raise HTTPException(400, "Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)

"""Shared helpers for route modules: auth guards, catalog HTTP mapping, job glue.

Path resolution uses ``infrastructure.files.workspace`` directly — no thin re-export
wrappers around ``board_root`` / ``workspace_dir``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import markdown as md
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select

from auth.middleware import require_user
from jobs import cost_ledger, pipeline_adapters
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from jobs.runner import get_runner
from models.core import OwnedBoardRecord, UserRecord
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws

from assets import services as asset_urls
from boards import services as bd
from prompts import live_source as live_source_svc
from boards import repository as board_ownership

from prompts import live as live_prompt_svc
from infrastructure import board_store as bs

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
SPEC_PROSE_PATH = REPO_ROOT / "docs" / "spec_prose.md"


def safe_next(next_path: str | None) -> str:
    """Whitelist the redirect target — only allow same-origin absolute paths."""
    if not next_path:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if next_path.startswith("/login") or next_path.startswith("/register"):
        return "/"
    return next_path


def _resolve_segment_to_canonical_uuid(user_id: str, segment: str) -> str:
    """Return ``board_games.id`` (UUID string) for legacy ``/b/<slug>/`` URLs.

    Nested routes already pass a UUID; slug-shaped segments resolve via
    ``owned_boards.path_slug`` for this user.
    """
    s = (segment or "").strip()
    if bf_boards.is_board_uuid(s):
        return s
    if not bf_boards.is_valid_id(s):
        return s
    with session_scope() as session:
        row = session.scalar(
            select(OwnedBoardRecord).where(
                OwnedBoardRecord.user_id == user_id,
                func.lower(OwnedBoardRecord.path_slug) == s.lower(),
            )
        )
    if row is not None:
        return row.board_uuid
    return s


def board_on_disk_or_404(board_id: str) -> bf_boards.BoardInfo:
    if not (bf_boards.is_board_uuid(board_id) or bf_boards.is_valid_id(board_id)):
        raise HTTPException(400, "Invalid board id")
    info = bf_boards.get_board(board_id)
    if info is None:
        raise HTTPException(404, f"Unknown board {board_id!r}")
    return info


def board_url_parts(board_id: str) -> tuple[str, str] | None:
    """Return ``(username, url_segment)`` for canonical board URLs, or ``None``.

    The URL segment is ``owned_boards.path_slug`` (the slug chosen at creation).
    """
    with session_scope() as session:
        ob = session.get(OwnedBoardRecord, board_id)
        if ob is None:
            return None
        ur = session.get(UserRecord, ob.user_id)
        if ur is None:
            return None
        return (ur.username, ob.path_slug)


def board_http_prefix(board_id: str) -> str:
    """URL prefix for board-scoped HTTP paths (nested REST shape when possible)."""
    parts = board_url_parts(board_id)
    if parts:
        u, p = parts
        return f"/users/{u}/board-games/{p}"
    return f"/b/{board_id}"


def canonical_board_base_path(board_id: str) -> str:
    """``/users/<username>/board-games/<board_id>`` without trailing slash."""
    parts = board_url_parts(board_id)
    if parts is None:
        raise HTTPException(404, "Unknown board")
    u, p = parts
    return f"/users/{u}/board-games/{p}"


def redirect_legacy_board_get(request: Request, board_id: str, rest: str = "") -> RedirectResponse:
    """307 from ``/b/<id>/…`` to canonical ``/users/<username>/board-games/<slug>/…``."""
    info = ensure_owned_board(request, board_id)
    base = canonical_board_base_path(info.id)
    tail = (rest or "").strip("/")
    dest = f"{base}/{tail}" if tail else f"{base}/"
    q = request.url.query
    if q:
        dest = f"{dest}?{q}"
    return RedirectResponse(dest, status_code=307)


def resolve_owned_board_path(request: Request, username: str, path_slug: str) -> str:
    """Resolve nested URL segments to ``board_id``; enforce URL matches logged-in user.

    Accepts the canonical segment (``board_id``) or a legacy ``path_slug`` stored
    when the board was created under the old title-based slug scheme.
    """
    un = (username or "").strip().lower()
    seg = (path_slug or "").strip().lower()
    user = require_user(request)
    if user.username != un:
        raise HTTPException(404, "Unknown board")
    with session_scope() as session:
        row = session.scalar(
            select(OwnedBoardRecord).where(
                OwnedBoardRecord.user_id == user.id,
                or_(
                    func.lower(OwnedBoardRecord.board_uuid) == seg,
                    func.lower(OwnedBoardRecord.path_slug) == seg,
                ),
            )
        )
    if row is None:
        raise HTTPException(404, "Unknown board")
    return row.board_uuid


def require_nested_board(request: Request, username: str, path_slug: str) -> str:
    """``Depends`` target for ``/users/{username}/board-games/{path_slug}/…`` routes."""
    return resolve_owned_board_path(request, username, path_slug)


def ensure_owned_board(request: Request, board_id: str) -> bf_boards.BoardInfo:
    user = require_user(request)
    uid = _resolve_segment_to_canonical_uuid(user.id, board_id)
    info = board_on_disk_or_404(uid)
    if not board_ownership.user_owns_board(user.id, uid):
        raise HTTPException(404, f"Unknown board {board_id!r}")
    return info


def load_board_catalog(board_id: str) -> dict[str, Any]:
    try:
        return bd.load_catalog(board_id)
    except bd.CatalogNotFound:
        raise HTTPException(404, f"Catalog not found for board {board_id!r}")


def accepts_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept


def job_or_redirect_response(
    request: Request, job_id: str, redirect_to: str = "/",
) -> JSONResponse | RedirectResponse:
    if accepts_json(request):
        return JSONResponse({"job_id": job_id})
    return RedirectResponse(redirect_to, status_code=303)


def editorial_template_context(board_id: str | None, request: Request | None = None) -> dict:
    project = "Board Factory"
    if board_id:
        # Catalog is the source of truth for the project title; fall back to
        # the on-disk ``BoardInfo`` (which uses the id) for boards that are on
        # disk but not yet persisted in the DB.
        row = bd.load_catalog_dict(board_id)
        if row is not None:
            project = str(row.get("project") or board_id)
        else:
            info = bf_boards.get_board(board_id)
            if info:
                project = info.project
    user = getattr(request.state, "user", None) if request is not None else None
    board_base = None
    if board_id:
        parts = board_url_parts(board_id)
        if parts:
            un, ps = parts
            board_base = f"/users/{un}/board-games/{ps}"
    return {
        "board_id": board_id,
        "board_base": board_base,
        "project": project,
        "has_palette": fs_ws.has_palette(board_id) if board_id else False,
        "cost": cost_ledger.summary(),
        "estimates": pipeline_cost_estimates() if board_id
        else {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict() if user else None,
    }


def pipeline_cost_estimates() -> dict:
    return {
        "spaces": pipeline_adapters.estimate_generate("spaces"),
        "panels": pipeline_adapters.estimate_generate("panels"),
        "centerpiece": pipeline_adapters.estimate_generate("centerpiece"),
    }


def enqueue_pipeline_job(
    *, label: str, operation: str, target: str | None, cost_estimate: float, fn,
) -> str:
    """Register a pipeline ``fn`` on the runner's worker pool. Returns the job id."""
    job = get_runner().enqueue(
        label=label,
        operation=operation,
        target=target,
        cost_estimate=cost_estimate,
        fn=fn,
    )
    return job.id


def scoped_pipeline_callable(board_id: str, fn: Callable) -> Callable:
    """Wrap ``fn`` so it executes inside ``config.scope_board(board_id)``.

    ``scope_board`` takes the per-board write lock for the lifetime of the
    job, serializing concurrent jobs that target the same board. Read-only
    code paths (e.g. the side-panel ``/api/cell`` fetch) use
    ``config.set_active_board`` instead so they never block on a job in
    flight for the same board.

    Also materializes the persisted style-lock palette to disk before the
    pipeline reads it.
    """
    def wrapped(job, cancel):
        with bf_config.scope_board(board_id):
            try:
                from boards import palette as _wp

                _wp.materialize_palette_to_disk(board_id)
            except Exception:
                pass
            return fn(job, cancel)

    return wrapped


def user_provider_api_keys(request: Request) -> dict[str, str]:
    u = getattr(request.state, "user", None)
    keys: dict[str, str] = {}
    if u:
        if u.pixellab_api_key:
            keys["pixellab_key"] = u.pixellab_api_key
        if u.openai_api_key:
            keys["openai_key"] = u.openai_api_key
    return keys


def load_spec_prose_sections() -> dict[str, str]:
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


def candidates_per_regen_count(category: str) -> int:
    return bf_config.regen_candidate_count(category)


def build_cell_side_panel_payload(board_id: str, category: str, asset_id: str) -> dict:
    """JSON state for one cell: spec + live url + history list (with prompts)."""
    catalog = load_board_catalog(board_id)
    bpath = board_http_prefix(board_id)

    spec: dict = {}
    if category == "spaces":
        designs = catalog.get("board_spaces", {}).get("designs", [])
        d = next((x for x in designs if x["id"] == asset_id), None)
        if d is None:
            raise HTTPException(404, f"Unknown space design: {asset_id}")
        from views.board_svg import _resolve_position

        layout = catalog["board_spaces"]["layout"]
        sample_pos = d["positions"][0] if d.get("positions") else None
        size = None
        if sample_pos:
            _x, _y, w, h = _resolve_position(layout, sample_pos)
            size = [w, h]
        spec = {
            "id": d["id"],
            "title": d["id"].replace("_", " "),
            "prompt": d.get("prompt", ""),
            "uses": len(d.get("positions", [])),
            "size": size,
            "kind": "space",
            "space_kind": d.get("space_kind") or "standard",
        }
    elif category == "panels":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == asset_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel: {asset_id}")
        spec = {
            "id": p["id"],
            "title": p["id"].replace("_", " "),
            "prompt": p.get("prompt", ""),
            "uses": 1,
            "size": list(p["target_size"]),
            "kind": "panel",
        }
    elif category == "centerpiece":
        cp = catalog["centerpiece"]
        spec = {
            "id": "centerpiece",
            "title": "Centerpiece",
            "prompt": cp.get("prompt", ""),
            "uses": 1,
            "size": list(cp["target_size"]),
            "kind": "centerpiece",
        }
    else:
        raise HTTPException(400, f"Unknown category {category}")

    # Read-only history listing — set the thread-local active board without
    # taking the per-board write lock. Otherwise this fetch would block on
    # any in-flight pipeline job for the same board, freezing the side panel
    # while a single space generates.
    with bf_config.set_active_board(board_id):
        from boardfactory import assets as bf_assets

        entries = bf_assets.list_history(category, asset_id)

    history = [
        {
            "filename": e.filename,
            "ts_ms": e.timestamp_ms,
            "seq": e.seq,
            "is_live": e.is_live,
            "operation": e.operation,
            "prompt": e.prompt,
            "url": f"{bpath}/asset/history/{category}/{asset_id}/{e.filename}",
        }
        for e in entries
    ]

    live_rel = fs_ws.live_rel(category, asset_id)
    store = bs.get_store()
    live_url = None
    if store.exists(board_id, live_rel):
        live_url = asset_urls.board_asset_url(
            http_prefix=bpath,
            asset_relpath=live_rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, live_rel).mtime_ms,
        )

    catalog_prompt = spec.get("prompt", "") or ""
    active_prompt = live_prompt_svc.resolve_active_prompt(
        board_id,
        category,
        asset_id,
        entries=entries,
        catalog_prompt=catalog_prompt,
    )
    ptr = live_source_svc.read_live_source(board_id, category, asset_id)
    live_history_filename = ptr.history_filename if ptr is not None else None

    frame_block = catalog.get("frame", {}) or {}
    frame_enabled_for_cell = (
        category == "panels"
        and bool(frame_block.get("enabled"))
        and bool(frame_block.get("apply_to_panels", True))
    )
    # Read-only frame metadata — same reasoning as the history block above.
    with bf_config.set_active_board(board_id):
        frame_present = bf_frames.has_house_frame()
        frame_meta = bf_frames.read_house_meta() if frame_present else None
    frame_locked = frame_enabled_for_cell and frame_present and store.exists(board_id, live_rel)

    frame_payload: dict | None = None
    if category == "panels":
        all_panels = catalog.get("feature_panels", {}).get("panels", [])
        panel_sources: list[dict] = []
        for p in all_panels:
            prel = fs_ws.live_rel("panels", p["id"])
            if not store.exists(board_id, prel):
                continue
            panel_sources.append(
                {
                    "id": p["id"],
                    "label": p["id"].replace("_", " "),
                    "size": list(p["target_size"]),
                    "url": asset_urls.board_asset_url(
                        http_prefix=bpath,
                        asset_relpath=prel.removeprefix("workspace/"),
                        mtime_ms=store.stat(board_id, prel).mtime_ms,
                    ),
                    "is_self": p["id"] == asset_id,
                }
            )

        mockup_source: dict | None = None
        ref_rel = (catalog.get("style") or {}).get("reference_image", "mockup/board.png")
        mockup_path = fs_ws.board_root(board_id) / ref_rel
        if mockup_path.exists():
            mockup_source = {
                "id": asset_id,
                "label": f"{asset_id.replace('_', ' ')} (from mockup)",
                "size": spec["size"],
                "url": (
                    f"{bpath}/api/frame/preview.png"
                    f"?source_kind=mockup&source_id={asset_id}"
                    f"&ring_px=8&w={spec['size'][0]}&h={spec['size'][1]}"
                ),
            }

        default_ring = max(4, min(spec["size"][0], spec["size"][1]) // 16)
        max_ring = max(default_ring, min(spec["size"][0], spec["size"][1]) // 3)

        frame_payload = {
            "supported": True,
            "enabled": bool(frame_block.get("enabled")),
            "adopted": frame_present,
            "adopted_meta": frame_meta.to_dict() if frame_meta else None,
            "applied_to_this_cell": frame_locked,
            "panel_sources": panel_sources,
            "mockup_source": mockup_source,
            "default_ring_px": default_ring,
            "min_ring_px": 2,
            "max_ring_px": max_ring,
            "preview_endpoint": f"{bpath}/api/frame/preview.png",
            "adopt_endpoint": f"{bpath}/api/frame/adopt",
            "disable_endpoint": f"{bpath}/api/frame/disable",
        }

    return {
        "board_id": board_id,
        "category": category,
        "asset_id": asset_id,
        "spec": spec,
        "live_url": live_url,
        "has_live": store.exists(board_id, live_rel),
        "history": history,
        "catalog_prompt": catalog_prompt,
        "active_prompt": active_prompt,
        "live_history_filename": live_history_filename,
        "regen_estimate_usd": pipeline_adapters.estimate_regen_one(category, asset_id),
        "candidates_per_regen": candidates_per_regen_count(category),
        "frame_locked": frame_locked,
        "frame_url": (
            f"{bpath}/frame.png?w={spec['size'][0]}&h={spec['size'][1]}"
            if frame_locked and spec.get("size")
            else None
        ),
        "frame": frame_payload,
    }

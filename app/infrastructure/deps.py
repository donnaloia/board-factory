"""Shared helpers for HTTP handlers: auth guards, catalog mapping, job glue.

Path resolution uses ``infrastructure.files.workspace`` directly — no thin re-export
wrappers around ``board_root`` / ``workspace_dir``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select

from auth.middleware import require_user
from jobs import cost_ledger
from domains.boards import pipeline_jobs as board_pipeline_jobs
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from jobs.runner import get_runner
from auth.models import UserRecord
from domains.boards.models import OwnedBoardRecord
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws

from domains.boards import services as bd

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def safe_next(next_path: str | None) -> str:
    """Whitelist the redirect target — only allow same-origin absolute paths."""
    if not next_path:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if next_path.startswith("/login") or next_path.startswith("/register"):
        return "/"
    return next_path


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
    """URL prefix for board-scoped HTTP paths: ``/users/<u>/board-games/<slug>``."""
    parts = board_url_parts(board_id)
    if parts is None:
        raise HTTPException(404, "Unknown board")
    u, p = parts
    return f"/users/{u}/board-games/{p}"


def canonical_board_base_path(board_id: str) -> str:
    """``/users/<username>/board-games/<board_id>`` without trailing slash."""
    parts = board_url_parts(board_id)
    if parts is None:
        raise HTTPException(404, "Unknown board")
    u, p = parts
    return f"/users/{u}/board-games/{p}"


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
        "spaces": board_pipeline_jobs.estimate_generate("spaces"),
        "panels": board_pipeline_jobs.estimate_generate("panels"),
        "centerpiece": board_pipeline_jobs.estimate_generate("centerpiece"),
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
                from domains.boards import palette as _wp

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
    from tech_spec.loader import load_spec_prose_sections as _load

    return _load()


def candidates_per_regen_count(category: str) -> int:
    return bf_config.regen_candidate_count(category)


# NOTE: ``build_cell_side_panel_payload`` lives in
# ``domains.spaces.services`` — the cell side panel is a spaces-domain
# concern, not shared infrastructure. Routes that used to import it from
# this module should now do ``from domains.spaces import services as
# spaces_services`` and call ``spaces_services.build_cell_side_panel_payload``.

"""Board Factory web application — multi-board operating room.

Boards live under data/boards/<id>/ on disk (resolved through the BoardStore),
mockup, and exports. Board-specific URLs use the nested form
``/users/<username>/board-games/<path_slug>/...``. The root ``/`` is a board picker.

Route handlers live in domain packages (e.g. ``domains.boards.routes_html``). Shared
FastAPI ``Depends`` helpers and request glue are in ``infrastructure.deps``.
This module assembles the FastAPI app, middleware, static files (``frontend/static``),
Jinja templates (``frontend/templates``), view helpers (``frontend/views``), and startup hooks.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from auth.middleware import AuthMiddleware
from domains.spaces.assets.routes_api import router as routes_assets
from domains.spaces.routes_api import router as routes_spaces
from domains.spaces.animations.routes_api import router as routes_space_animations
from auth.routes_html import router as auth_html_router
from auth.routes_api import router as auth_api_router
from domains.boards.routes_html import router as boards_html_router
from domains.boards.routes_api import router as boards_api_router
from domains.cards.routes_html import router as cards_html_router
from domains.cards.routes_api import router as cards_api_router
from domains.tokens.routes_html import router as tokens_html_router
from domains.tokens.routes_api import router as tokens_api_router
from jobs.routes_api import router as jobs_api_router

app = FastAPI(title="Board Factory")
app.add_middleware(AuthMiddleware)


@app.get("/health")
def health_check():
    """Anonymous lightweight probe — does not touch the DB."""
    return JSONResponse({"ok": True})


@app.get("/health/ready")
def health_ready():
    """Anonymous DB probe — distinguishes process-up vs Postgres wedged / unreachable."""
    from sqlalchemy import text

    from infrastructure.db import session_scope

    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=503)
    return JSONResponse({"ok": True})

TEMPLATES_DIR = Path(__file__).parent / "frontend" / "templates"
STATIC_DIR = Path(__file__).parent / "frontend" / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.state.templates = templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _asset_version(filename: str) -> str:
    """Content-hash of a static asset for cache-busting query strings."""
    p = STATIC_DIR / filename
    if not p.exists():
        return "0"
    return hashlib.sha1(p.read_bytes()).hexdigest()[:10]


templates.env.globals["asset_v"] = _asset_version


def _configure_observability_logging() -> None:
    """Ensure INFO lines from job runner + bootstrap reach stderr.

    Uvicorn configures root logging; children often still propagate at WARNING.
    We attach explicit handlers so pipeline/job lifecycle is visible in
    ``docker compose logs`` without guessing hangs vs slow network calls.
    """
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    for name in ("jobs.runner", "boot"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        if lg.handlers:
            continue
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        lg.addHandler(h)
        lg.propagate = False


@app.on_event("startup")
def startup() -> None:
    _configure_observability_logging()
    from boardfactory import config as bf_config  # noqa: PLC0415
    from domains.boards import repository as boards_repo  # noqa: PLC0415

    bf_config.set_board_root_resolver(boards_repo.store_board_root)

    import boot  # noqa: PLC0415

    boot.apply()


app.include_router(auth_html_router)
app.include_router(auth_api_router)
app.include_router(routes_assets)
app.include_router(boards_html_router)
app.include_router(boards_api_router)
app.include_router(cards_html_router)
app.include_router(cards_api_router)
app.include_router(routes_spaces)
app.include_router(routes_space_animations)
app.include_router(tokens_html_router)
app.include_router(tokens_api_router)
app.include_router(jobs_api_router)

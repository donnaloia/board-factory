"""Board Factory web application — multi-board operating room.

Boards live at boards/<id>/ on disk, each with its own catalog, workspace,
mockup, and exports. URLs are scoped: /b/<board_id>/... for everything
board-specific. The root / is a board picker.

Route handlers live under ``routes/``; this module assembles the FastAPI app,
middleware, static files, and startup hooks.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import auth
from routes import assets as routes_assets
from routes import auth as routes_auth
from routes import board as routes_board
from routes import home as routes_home
from routes import job_tray as routes_job_tray
from routes import legacy as routes_legacy
from routes import profile as routes_profile

app = FastAPI(title="Board Factory")
app.add_middleware(auth.AuthMiddleware)


@app.get("/health")
def health_check():
    """Anonymous lightweight probe — does not touch the DB."""
    return JSONResponse({"ok": True})


@app.get("/health/ready")
def health_ready():
    """Anonymous DB probe — distinguishes process-up vs Postgres wedged / unreachable."""
    from sqlalchemy import text

    from storage.db import session_scope

    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=503)
    return JSONResponse({"ok": True})

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
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
    for name in ("jobs", "storage.bootstrap"):
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
    from storage import bootstrap  # noqa: PLC0415

    bootstrap.apply()


app.include_router(routes_auth.router)
app.include_router(routes_profile.router)
app.include_router(routes_home.router)
app.include_router(routes_legacy.router)
app.include_router(routes_assets.router)
app.include_router(routes_board.router)
app.include_router(routes_job_tray.router)

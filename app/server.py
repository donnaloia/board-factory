"""Board Factory web application — multi-board operating room.

Boards live under data/boards/<id>/ on disk (resolved through the BoardStore),
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

from auth.middleware import AuthMiddleware
from assets import routes as routes_assets
from cells import routes as routes_cells
from routes import auth as routes_auth
from routes import board as routes_board
from routes import home as routes_home
from routes import job_tray as routes_job_tray
from routes import profile as routes_profile

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
    from boards import repository as boards_repo  # noqa: PLC0415

    bf_config.set_board_root_resolver(boards_repo.store_board_root)

    import boot  # noqa: PLC0415

    boot.apply()


app.include_router(routes_auth.router)
app.include_router(routes_profile.router)
app.include_router(routes_home.router)
app.include_router(routes_assets.router)
app.include_router(routes_board.router)
app.include_router(routes_cells.router)
app.include_router(routes_job_tray.router)

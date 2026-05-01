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
from fastapi import Depends, FastAPI, File, HTTPException, Request, Form, UploadFile
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

import auth
import sessions
import users
import pixellab_status

# Pipeline imports — these access config.PATH attributes lazily, so we just
# need to make sure config.set_board(...) is called before any of them run.
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
SPEC_PROSE_PATH = REPO_ROOT / "docs" / "spec_prose.md"
BOARDS_DIR = REPO_ROOT / "boards"

app = FastAPI(title="Board Factory Review")
app.add_middleware(auth.AuthMiddleware)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _asset_version(filename: str) -> str:
    """Short content-hash of a static asset, for cache-busting <link href=…?v=…>.

    Recomputed on import (i.e. on container start). The bind-mount makes the
    file change live, but Safari/Chrome can hold an aggressive cache without
    a query string. Stamping the hash forces a fresh fetch any time the file
    actually changes between deploys.
    """
    p = STATIC_DIR / filename
    if not p.exists():
        return "0"
    import hashlib
    return hashlib.sha1(p.read_bytes()).hexdigest()[:10]


# Expose to all templates as {{ asset_v('style.css') }}.
templates.env.globals["asset_v"] = _asset_version


# ────────────────────────── one-time bootstrap ──────────────────────────


@app.on_event("startup")
def startup() -> None:
    """One-shot migrations.

    Two things happen on every container start (idempotent — safe to re-run):

      1. The classic single-board flat layout (catalog/, workspace/, mockup/
         at repo root) gets folded into boards/damnation/ if no boards exist
         yet. This is the legacy from before multi-board support.

      2. For every existing board, anything in the legacy `approved/` flow
         gets seeded into `live/` + `history/`, then the legacy directories
         (`candidates/`, `cleaned/`, `approved/`) are deleted. The web app
         only knows about `live/` + `history/` now; the old dirs were the
         CLI's working space and have nothing the user hasn't already
         decided about.
    """
    bf_boards.migrate_legacy_flat_layout(target_board_id="damnation")

    from boardfactory import assets as bf_assets

    for info in bf_boards.list_boards():
        if not info.has_catalog:
            continue
        try:
            with bf_config.scope_board(info.id):
                catalog = _load_catalog(info.id)
                seed_count = 0
                seed_failures: list[str] = []
                ids: list[tuple[str, str]] = []
                for d in catalog.get("board_spaces", {}).get("designs", []):
                    ids.append(("spaces", d["id"]))
                for p in catalog.get("feature_panels", {}).get("panels", []):
                    ids.append(("panels", p["id"]))
                ids.append(("centerpiece", "centerpiece"))

                for cat, aid in ids:
                    try:
                        result = bf_assets.seed_from_legacy_approved(cat, aid)
                        if result is not None:
                            seed_count += 1
                    except Exception as e:
                        seed_failures.append(f"{cat}/{aid}: {e}")

                if seed_failures:
                    print(
                        f"[migrate] board={info.id} "
                        f"seeded={seed_count} but skipped purge "
                        f"due to {len(seed_failures)} seed failure(s)"
                    )
                    for f in seed_failures[:5]:
                        print(f"[migrate]   FAIL: {f}")
                    continue

                removed = bf_assets.purge_legacy_dirs()
                if seed_count or removed:
                    print(
                        f"[migrate] board={info.id} "
                        f"seeded={seed_count} purged={','.join(removed) or '(none)'}"
                    )
        except Exception as e:
            print(f"[migrate] board={info.id} ERROR: {e}")


# ────────────────────────── routes: auth ──────────────────────────


def _safe_next(next_path: str | None) -> str:
    """Whitelist the redirect target — only allow same-origin absolute paths.
    Prevents open-redirect via /login?next=https://evil.example."""
    if not next_path:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if next_path.startswith("/login") or next_path.startswith("/register"):
        return "/"
    return next_path


@app.get("/login", response_class=HTMLResponse)
def login_view(request: Request, next: str | None = None,
               error: str | None = None, info: str | None = None):
    if users.is_setup_required():
        # No accounts yet → registration page is the only valid entry point.
        return RedirectResponse("/register", status_code=303)
    return templates.TemplateResponse(request, "auth_login.html", {
        "next": _safe_next(next),
        "error": error,
        "info": info,
    })


@app.post("/login")
def login_submit(request: Request, email: str = Form(...),
                 password: str = Form(...), next: str = Form(default="/")):
    user = users.find_by_email(email)
    if user is None or not users.verify_password(user, password):
        # Constant-ish-time-ish: bcrypt verify already takes ~hundreds of ms,
        # so the find_by_email path doesn't open a meaningful timing oracle.
        return RedirectResponse(
            f"/login?next={_safe_next(next)}&error=Invalid+email+or+password",
            status_code=303,
        )
    cookie = sessions.create(user.id)
    users.touch_last_login(user.id)
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        sessions.COOKIE_NAME, cookie,
        httponly=True, samesite="lax", max_age=sessions.SESSION_TTL_SEC,
    )
    return response


@app.post("/logout")
def logout_submit(request: Request):
    cookie_value = request.cookies.get(sessions.COOKIE_NAME)
    sessions.destroy(cookie_value)
    response = RedirectResponse("/login?info=Signed+out", status_code=303)
    response.delete_cookie(sessions.COOKIE_NAME)
    return response


@app.get("/register", response_class=HTMLResponse)
def register_view(request: Request, error: str | None = None):
    # First-user-only: if any user exists, registration is closed.
    if not users.is_setup_required():
        return RedirectResponse(
            "/login?info=Registration+is+closed", status_code=303,
        )
    return templates.TemplateResponse(request, "auth_register.html", {
        "error": error,
    })


@app.post("/register")
def register_submit(request: Request, email: str = Form(...),
                    password: str = Form(...), display_name: str = Form(default="")):
    if not users.is_setup_required():
        # Race-guard: another tab created the account in the meantime.
        return RedirectResponse(
            "/login?info=Registration+is+closed", status_code=303,
        )
    try:
        user = users.create_first_user(
            email=email, password=password, display_name=display_name or None,
        )
    except ValueError as e:
        return RedirectResponse(
            f"/register?error={str(e).replace(' ', '+')}", status_code=303,
        )
    cookie = sessions.create(user.id)
    users.touch_last_login(user.id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        sessions.COOKIE_NAME, cookie,
        httponly=True, samesite="lax", max_age=sessions.SESSION_TTL_SEC,
    )
    return response


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_view(request: Request, sent: bool = False):
    return templates.TemplateResponse(request, "auth_forgot.html", {"sent": sent})


@app.post("/forgot-password")
def forgot_submit(request: Request, email: str = Form(...)):
    # Intentional stub. We don't send mail. Return a generic success regardless
    # of whether the email exists — same UX you'd see if we did wire SMTP.
    return RedirectResponse("/forgot-password?sent=true", status_code=303)


# ────────────────────────── routes: account modal API ──────────────────────────


@app.get("/api/profile")
def api_profile_get(request: Request):
    user = auth.require_user(request)
    return JSONResponse({
        **user.public_dict(),
        "glyphs": users.GLYPHS,
        "default_glyph": users.DEFAULT_GLYPH,
        "default_color": users.DEFAULT_COLOR,
    })


@app.put("/api/profile")
async def api_profile_update(request: Request):
    user = auth.require_user(request)
    body = await request.json()
    try:
        updated = users.update_profile(
            user.id,
            display_name=body.get("display_name"),
            email=body.get("email"),
            icon_glyph=body.get("icon_glyph"),
            icon_color=body.get("icon_color"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(updated.public_dict())


@app.put("/api/profile/api-key")
async def api_profile_api_key(request: Request):
    """Update one or both image-gen API keys.

    Body: { "pixellab_api_key"?: str, "openai_api_key"?: str }

    Per-field omission means "no change" (see users.update_api_keys docstring).
    The modal sends both fields when the artist hits "Save image-gen keys",
    using "" to clear and the actual value to set. We never echo the raw key
    back — the response is the masked public projection.
    """
    user = auth.require_user(request)
    body = await request.json()
    try:
        updated = users.update_api_keys(
            user.id,
            pixellab_api_key=body.get("pixellab_api_key"),
            openai_api_key=body.get("openai_api_key"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(updated.public_dict())


@app.post("/api/profile/password")
async def api_profile_password(request: Request):
    user = auth.require_user(request)
    body = await request.json()
    try:
        users.change_password(
            user.id,
            old=body.get("current_password", ""),
            new=body.get("new_password", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Invalidate all other sessions on password change.
    sessions.destroy_all_for_user(user.id)
    # …but immediately mint a fresh one for this browser so the user stays
    # signed in on the page they're on.
    new_cookie = sessions.create(user.id)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        sessions.COOKIE_NAME, new_cookie,
        httponly=True, samesite="lax", max_age=sessions.SESSION_TTL_SEC,
    )
    return response


@app.get("/api/profile/api-status")
async def api_profile_status(request: Request):
    user = auth.require_user(request)
    report = await pixellab_status.run_status_checks(user.pixellab_api_key)
    return JSONResponse(report.to_dict())


@app.get("/api/profile/openai-status")
async def api_openai_status(request: Request):
    """Ping the OpenAI API with the user's key to verify it works.

    Uses the cheapest possible call: list available models (no tokens spent).
    Returns { ok, detail } so the client can update the live-connection dot.
    """
    user = auth.require_user(request)
    key = user.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return JSONResponse({"ok": False, "detail": "no key saved"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        if r.status_code == 200:
            return JSONResponse({"ok": True, "detail": "connected"})
        if r.status_code == 401:
            return JSONResponse({"ok": False, "detail": "invalid key"})
        return JSONResponse({"ok": False, "detail": f"HTTP {r.status_code}"})
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)[:80]})


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


def _raw_candidates(board_id: str, category: str, asset_id: str | None = None) -> list[Path]:
    """Pre-cleanup raw candidates (workspace/candidates/...)."""
    base = _workspace(board_id) / "candidates" / category
    if asset_id:
        base = base / asset_id
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.png") if not p.name.startswith("_"))


def _has_generated_asset(board_id: str, category: str, asset_id: str) -> bool:
    """Truthy when this cell has a *live* asset the user has accepted, or a
    legacy approved asset that auto-seeds into live on next view.

    This intentionally does NOT count raw candidates or untouched history —
    those are by-products of an earlier broad-stroke run that the user may
    have abandoned without promoting any version. From the artist's POV the
    cell is still empty until something is on the board, so 'Generate
    missing spaces' should re-run for it.
    """
    if _live_path(board_id, category, asset_id).exists():
        return True
    # Legacy approved/<id>.png seeds into live/ on the next render via
    # _seed_history_if_needed, so treat it as already-live.
    if _approved_path(board_id, category, asset_id).exists():
        return True
    return False


def _missing_space_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        d["id"]
        for d in catalog.get("board_spaces", {}).get("designs", [])
        if not _has_generated_asset(board_id, "spaces", d["id"])
    ]


def _missing_panel_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        p["id"]
        for p in catalog.get("feature_panels", {}).get("panels", [])
        if not _has_generated_asset(board_id, "panels", p["id"])
    ]


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


def _save_catalog(board_id: str, data: dict) -> None:
    """Atomic write of the catalog YAML."""
    p = _catalog_path(board_id)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp, p)


def _generation_defaults() -> dict:
    """Default generation block for boards that don't have one yet."""
    return {
        "palette_size": 36,
        "provider": "openai",
        "openai": {"model": "gpt-image-2", "quality": "low"},
        "pixellab": {"model": "pixflux_sharp"},
        "configured": False,
    }


def _read_generation(catalog: dict) -> dict:
    """Return the generation block, filling defaults for missing fields."""
    block = dict(_generation_defaults())
    existing = catalog.get("generation") or {}
    if isinstance(existing, dict):
        if "palette_size" in existing:
            try:
                ps = int(existing["palette_size"])
                if 4 <= ps <= 64:
                    block["palette_size"] = ps
            except (TypeError, ValueError):
                pass
        if existing.get("provider") in ("openai", "pixellab", "mock"):
            block["provider"] = existing["provider"]
        oa = existing.get("openai") or {}
        if isinstance(oa, dict):
            if oa.get("model") in ("gpt-image-1", "gpt-image-2"):
                block["openai"]["model"] = oa["model"]
            if oa.get("quality") in ("low", "medium", "high"):
                block["openai"]["quality"] = oa["quality"]
        pl = existing.get("pixellab") or {}
        if isinstance(pl, dict):
            from boardfactory.providers.pixel.pixellab import PIXELLAB_PRESETS
            if pl.get("model") in PIXELLAB_PRESETS:
                block["pixellab"]["model"] = pl["model"]
        if "configured" in existing:
            block["configured"] = bool(existing["configured"])
    return block


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
        live_url = f"/b/{board_id}/asset/{rel.as_posix()}?t={int(live.stat().st_mtime)}"

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


def _base_context(board_id: str | None, request: Request | None = None) -> dict:
    """Common context for every editorial template — the cost meter is global,
    everything else scopes to the board if there is one."""
    project = "Board Factory"
    if board_id:
        info = bf_boards.get_board(board_id)
        if info:
            project = info.project
    user = getattr(request.state, "user", None) if request is not None else None
    return {
        "board_id": board_id,
        "project": project,
        "has_palette": _has_palette(board_id) if board_id else False,
        "cost": cost_ledger.summary(),
        "estimates": _estimates() if board_id else
                     {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
        "user": user.public_dict() if user else None,
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


def _user_keys(request: Request) -> dict[str, str]:
    """Return non-empty API keys saved by the requesting user."""
    u = getattr(request.state, "user", None)
    keys: dict[str, str] = {}
    if u:
        if u.pixellab_api_key:
            keys["pixellab_key"] = u.pixellab_api_key
        if u.openai_api_key:
            keys["openai_key"] = u.openai_api_key
    return keys


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
        ctx = _base_context(None, request)
        ctx.update({"boards": [], "has_any_board": False})
        return templates.TemplateResponse(request, "boards_index.html", ctx)

    if len(boards) == 1:
        return RedirectResponse(f"/b/{boards[0].id}/", status_code=303)

    ctx = _base_context(None, request)
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


@app.get("/b/{board_id}/api/generation")
def api_generation_get(board_id: str):
    """Return the current generation settings + the menu of available choices.

    The UI uses this both to populate the modal and to show the summary on the
    board page. Available models / presets are listed here so the modal stays
    in lockstep with what the providers actually accept.
    """
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)
    settings = _read_generation(catalog)
    from boardfactory.providers.pixel.pixellab import list_pixellab_presets

    return JSONResponse({
        "settings": settings,
        "options": {
            "palette_sizes": [24, 36],
            "providers": ["openai", "pixellab"],
            "openai_models": ["gpt-image-1", "gpt-image-2"],
            "openai_qualities": ["low", "medium", "high"],
            "pixellab_models": list_pixellab_presets(),
        },
    })


@app.put("/b/{board_id}/api/generation")
async def api_generation_put(request: Request, board_id: str):
    """Save the generation settings for a board.

    Body: { palette_size, provider, openai: {model, quality}, pixellab: {model} }
    `configured` is set to True automatically the first time we save.
    """
    _ensure_board_or_404(board_id)
    body = await request.json()
    catalog = _load_catalog(board_id)
    current = _read_generation(catalog)

    from boardfactory.providers.pixel.pixellab import PIXELLAB_PRESETS

    palette_size = body.get("palette_size", current["palette_size"])
    try:
        palette_size = int(palette_size)
    except (TypeError, ValueError):
        raise HTTPException(400, "palette_size must be an integer")
    if palette_size not in (24, 36):
        raise HTTPException(400, "palette_size must be 24 or 36")

    provider = body.get("provider", current["provider"])
    if provider not in ("openai", "pixellab"):
        raise HTTPException(400, "provider must be 'openai' or 'pixellab'")

    oa = body.get("openai") or {}
    oa_model = oa.get("model", current["openai"]["model"])
    if oa_model not in ("gpt-image-1", "gpt-image-2"):
        raise HTTPException(400, "openai.model must be 'gpt-image-1' or 'gpt-image-2'")
    oa_quality = oa.get("quality", current["openai"]["quality"])
    if oa_quality not in ("low", "medium", "high"):
        raise HTTPException(400, "openai.quality must be low/medium/high")

    pl = body.get("pixellab") or {}
    pl_model = pl.get("model", current["pixellab"]["model"])
    if pl_model not in PIXELLAB_PRESETS:
        raise HTTPException(400, f"pixellab.model must be one of {list(PIXELLAB_PRESETS)}")

    new_block = {
        "palette_size": palette_size,
        "provider": provider,
        "openai": {"model": oa_model, "quality": oa_quality},
        "pixellab": {"model": pl_model},
        "configured": True,
    }
    catalog["generation"] = new_block
    # Mirror palette_size into legacy style block too — older steps still read it.
    style = catalog.setdefault("style", {})
    style["palette_size"] = palette_size
    _save_catalog(board_id, catalog)
    return JSONResponse({"settings": new_block})


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
    missing_space_ids = _missing_space_ids(board_id, catalog)
    missing_panel_ids = _missing_panel_ids(board_id, catalog)
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

    ctx = _base_context(board_id, request)
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
        "generation": _read_generation(catalog),
    })
    return templates.TemplateResponse(request, "board.html", ctx)


@app.get("/b/{board_id}/setup", response_class=HTMLResponse)
def setup_view(request: Request, board_id: str):
    _ensure_board_or_404(board_id)
    mockup_present, mockup_rel = _mockup_present(board_id)
    ctx = _base_context(board_id, request)
    ctx.update({"mockup_present": mockup_present, "mockup_rel": mockup_rel})
    return templates.TemplateResponse(request, "setup.html", ctx)


@app.post("/b/{board_id}/actions/upload-mockup")
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
    _ensure_board_or_404(board_id)

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

    mockup_dir = _board_root(board_id) / "mockup"
    mockup_dir.mkdir(parents=True, exist_ok=True)
    dest = mockup_dir / "board.png"

    img.convert("RGB").save(dest, format="PNG")

    return JSONResponse({
        "ok": True,
        "size": [w, h],
        "warn_aspect": warn,
        "redirect": f"/b/{board_id}/setup",
    })


@app.get("/b/{board_id}/spec", response_class=HTMLResponse)
def spec_view(request: Request, board_id: str):
    """Live tech spec from the board's catalog + the shared prose markdown."""
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)
    prose = _load_spec_prose()
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
        "has_palette": _has_palette(board_id),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
        "user": user.public_dict() if user else None,
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

    ctx = _base_context(board_id, request)
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
    ctx = _base_context(board_id, request)
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


@app.get("/b/{board_id}/device-preview", response_class=HTMLResponse)
def device_preview_view(request: Request, board_id: str):
    """Show the composited board inside renderings of physical screens.

    Renders the same workspace/preview/board_*.png the compositor produces
    inside CSS mockups of TV / desktop / laptop / Switch / Steam Deck so
    the board can be sanity-checked at multiple form factors without
    leaving the browser.
    """
    _ensure_board_or_404(board_id)
    preview_dir = _workspace(board_id) / "preview"
    idle_path = preview_dir / "board_idle.png"
    active_path = preview_dir / "board_active.png"

    def _asset_url(name: str, p: Path) -> str:
        return f"/b/{board_id}/asset/preview/{name}?t={int(p.stat().st_mtime)}"

    idle_url = _asset_url("board_idle.png", idle_path) if idle_path.exists() else None
    active_url = _asset_url("board_active.png", active_path) if active_path.exists() else None

    catalog = _load_catalog(board_id)
    bw, bh = catalog.get("board_size", [1920, 1080])

    ctx = _base_context(board_id, request)
    ctx.update({
        "idle_url": idle_url,
        "active_url": active_url,
        "preview_present": bool(idle_url or active_url),
        "board_w": bw,
        "board_h": bh,
    })
    return templates.TemplateResponse(request, "device_preview.html", ctx)


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


@app.post("/b/{board_id}/actions/analyze")
async def action_analyze(request: Request, board_id: str):
    """Send the board mockup to GPT-4o vision and auto-fill every catalog prompt.

    Key resolution (first found wins):
      1. The requesting user's saved openai_api_key
      2. OPENAI_API_KEY environment variable
    If neither is set, returns 400 so the UI can surface a clear message.
    """
    _ensure_board_or_404(board_id)

    user = auth.current_user(request)
    openai_key = (user.openai_api_key if user else "") or os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(
            400,
            "No OpenAI API key found. Save one in Account → Connections → OpenAI / ChatGPT."
        )

    job_id = _enqueue(
        label="Analyze mockup with GPT-4o",
        operation="analyze", target=board_id,
        cost_estimate=pipeline_adapters.ANALYZE_COST_USD,
        fn=_scoped_fn(board_id, pipeline_adapters.analyze_adapter(openai_key)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


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
    """Generate every cell in this category that doesn't have a live asset yet.

    The button label distinguishes "Generate all X" from "Generate missing X"
    based on whether anything is already live; both routes converge here so
    the back-end behavior is identical: skip cells that already have art,
    only spend on what's actually missing.
    """
    _ensure_board_or_404(board_id)
    if category not in ("spaces", "panels", "centerpiece"):
        raise HTTPException(400, f"Unknown category {category}")
    keys = _user_keys(request)
    job_id = _enqueue(
        label=f"Generate missing {category}",
        operation=f"generate.{category}", target=board_id,
        cost_estimate=pipeline_adapters.estimate_generate(category),
        fn=_scoped_fn(board_id, pipeline_adapters.generate_missing_adapter(category, **keys)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/generate-missing/spaces")
async def action_generate_missing_spaces(request: Request, board_id: str):
    """Alias for /actions/generate/spaces kept for the existing UI button.

    Both routes funnel through generate_missing_adapter("spaces"), which
    skips designs with a live asset and only spends on what's empty.
    """
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)
    missing_space_ids = _missing_space_ids(board_id, catalog)
    count = len(missing_space_ids)
    keys = _user_keys(request)
    job_id = _enqueue(
        label=f"Generate {count} missing space{'s' if count != 1 else ''}",
        operation="generate.spaces", target=board_id,
        cost_estimate=pipeline_adapters.estimate_generate_one("spaces") * count,
        fn=_scoped_fn(board_id, pipeline_adapters.generate_missing_adapter("spaces", **keys)),
    )
    return _action_response(request, job_id, redirect_to=f"/b/{board_id}/")


@app.post("/b/{board_id}/actions/generate-missing/all")
async def action_generate_missing_all(request: Request, board_id: str):
    """Generate every empty board space AND every empty UI panel in one job."""
    _ensure_board_or_404(board_id)
    catalog = _load_catalog(board_id)
    missing_spaces = _missing_space_ids(board_id, catalog)
    missing_panels = _missing_panel_ids(board_id, catalog)
    total = len(missing_spaces) + len(missing_panels)
    keys = _user_keys(request)
    job_id = _enqueue(
        label=f"Generate {total} missing asset{'s' if total != 1 else ''}",
        operation="generate.all", target=board_id,
        cost_estimate=pipeline_adapters.estimate_generate_all(
            len(missing_spaces), len(missing_panels)
        ),
        fn=_scoped_fn(board_id, pipeline_adapters.generate_all_adapter(**keys)),
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
    keys = _user_keys(request)
    job_id = _enqueue(
        label=f"Regenerate {asset_id}",
        operation=f"regen.{category}", target=asset_id,
        cost_estimate=pipeline_adapters.estimate_generate_one(category, asset_id),
        fn=_scoped_fn(board_id,
                      pipeline_adapters.generate_one_adapter(category, asset_id,
                                                             prompt_override=p, **keys)),
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
        fn=_scoped_fn(board_id, pipeline_adapters.clean_one_adapter(category, asset_id)),
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

    # ────────── Frame info — only meaningful for panel cells ──────────
    frame_block = catalog.get("frame", {}) or {}
    frame_enabled_for_cell = (
        category == "panels"
        and bool(frame_block.get("enabled"))
        and bool(frame_block.get("apply_to_panels", True))
    )
    with bf_config.scope_board(board_id):
        frame_present = bf_frames.has_house_frame()
        frame_meta = bf_frames.read_house_meta() if frame_present else None
    frame_locked = frame_enabled_for_cell and frame_present and live.exists()

    frame_payload: dict | None = None
    if category == "panels":
        # Build the per-panel frame picker context: what's adopted now, and
        # what sources are available to extract a new frame from. The picker
        # only renders inline in the side panel, so we ship the data even if
        # the frame is currently disabled — the user might want to enable it.
        all_panels = catalog.get("feature_panels", {}).get("panels", [])
        panel_sources: list[dict] = []
        for p in all_panels:
            p_live = _live_path(board_id, "panels", p["id"])
            if p_live.exists():
                panel_sources.append({
                    "id": p["id"],
                    "label": p["id"].replace("_", " "),
                    "size": list(p["target_size"]),
                    "url": (
                        f"/b/{board_id}/asset/"
                        f"{p_live.relative_to(_workspace(board_id)).as_posix()}"
                        f"?t={int(p_live.stat().st_mtime)}"
                    ),
                    "is_self": p["id"] == asset_id,
                })

        # Mockup source — always available for THIS panel's bbox slice.
        mockup_source: dict | None = None
        ref_rel = (catalog.get("style") or {}).get("reference_image", "mockup/board.png")
        mockup_path = _board_root(board_id) / ref_rel
        if mockup_path.exists():
            mockup_source = {
                "id": asset_id,
                "label": f"{asset_id.replace('_', ' ')} (from mockup)",
                "size": spec["size"],
                "url": f"/b/{board_id}/api/frame/preview.png"
                       f"?source_kind=mockup&source_id={asset_id}"
                       f"&ring_px=8&w={spec['size'][0]}&h={spec['size'][1]}",
            }

        # Reasonable default ring thickness: ~6% of the smaller side, clamped
        # so the slider lands somewhere visible regardless of asset size.
        default_ring = max(4, min(spec["size"][0], spec["size"][1]) // 16)
        max_ring = max(default_ring, min(spec["size"][0], spec["size"][1]) // 3)

        frame_payload = {
            "supported": True,
            "enabled": bool(frame_block.get("enabled")),
            "adopted": frame_present,
            "adopted_meta": frame_meta.to_dict() if frame_meta else None,
            "applied_to_this_cell": frame_locked,
            # Picker inputs:
            "panel_sources": panel_sources,
            "mockup_source": mockup_source,
            "default_ring_px": default_ring,
            "min_ring_px": 2,
            "max_ring_px": max_ring,
            # On-demand image endpoints the picker drives:
            "preview_endpoint": f"/b/{board_id}/api/frame/preview.png",
            "adopt_endpoint": f"/b/{board_id}/api/frame/adopt",
            "disable_endpoint": f"/b/{board_id}/api/frame/disable",
        }

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
        "frame": frame_payload,
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
    return FileResponse(target, headers={"Cache-Control": "no-store"})


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

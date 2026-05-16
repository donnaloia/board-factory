"""Token Factory HTML routes — index (list) and detail (single token)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.middleware import require_user
from jobs import cost_ledger
from domains.tokens import services as svc_tokens
from domains.tokens import workspace as token_ws

router = APIRouter()


def _token_asset_base(username: str, path_slug: str) -> str:
    return f"/users/{username}/token-factory/{path_slug}"


# ── token list ────────────────────────────────────────────────────────────────

@router.get("/token-factory/", response_class=HTMLResponse)
def token_factory_index(request: Request):
    user = require_user(request)
    from domains.boards import services as svc_boards

    user_boards = svc_boards.list_boards(user.id)

    tokens_list = []
    for t in svc_tokens.list_tokens(user.id):
        asset_base = _token_asset_base(user.username, t.path_slug)
        canonical_exists = token_ws.canonical_png_path(t.id).exists()
        design_lock = token_ws.read_design_lock(t.id)
        preview_clip = svc_tokens.pick_preview_clip(
            t.id,
            t.locomotion_profile,
            token_asset_base=asset_base,
            design_lock=design_lock,
        )
        tokens_list.append(
            {
                "id": t.id,
                "path_slug": t.path_slug,
                "display_name": t.display_name or t.slug,
                "slug": t.slug,
                "locomotion_profile": t.locomotion_profile,
                "design_locked": t.design_locked,
                "canvas_w": t.canvas_w,
                "canvas_h": t.canvas_h,
                "frame_fps": t.frame_fps,
                "canonical_url": (
                    f"{asset_base}/asset/references/canonical.png"
                    if canonical_exists
                    else None
                ),
                "preview_clip": preview_clip,
            }
        )

    ctx = {
        "board_id": None,
        "board_base": None,
        "project": "Token Factory",
        "has_palette": False,
        "cost": cost_ledger.summary(),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict(),
        "tokens": tokens_list,
        "user_boards": [
            {
                "id": b.id,
                "project": b.project,
                "path_slug": b.path_slug,
            }
            for b in user_boards
        ],
    }
    resp = request.app.state.templates.TemplateResponse(
        request, "token_factory_index.html", ctx
    )
    resp.headers["Cache-Control"] = "private, no-store, must-revalidate"
    return resp


# ── token detail ──────────────────────────────────────────────────────────────

@router.get(
    "/users/{username}/token-factory/{path_slug}/", response_class=HTMLResponse
)
def token_factory_detail(request: Request, username: str, path_slug: str):
    user = require_user(request)
    if user.username != username:
        return RedirectResponse("/token-factory/", status_code=303)

    try:
        token = svc_tokens.get_token_by_path(user.id, path_slug)
    except svc_tokens.TokenNotFound:
        return RedirectResponse("/token-factory/", status_code=303)

    asset_base = _token_asset_base(username, path_slug)
    token_item = svc_tokens.build_token_detail_payload(
        token.id, token_asset_base=asset_base
    )

    from domains.boards import services as svc_boards
    user_boards = svc_boards.list_boards(user.id)

    ctx = {
        "board_id": None,
        "board_base": None,
        "project": token.display_name or token.slug,
        "has_palette": False,
        "cost": cost_ledger.summary(),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict(),
        "token_item": token_item,
        "user_boards": [
            {
                "id": b.id,
                "project": b.project,
                "path_slug": b.path_slug,
            }
            for b in user_boards
        ],
    }
    resp = request.app.state.templates.TemplateResponse(
        request, "token_factory_detail.html", ctx
    )
    resp.headers["Cache-Control"] = "private, no-store, must-revalidate"
    return resp


# ── legacy redirects ──────────────────────────────────────────────────────────

@router.get("/users/{username}/board-games/{path_slug}/tokens/")
def legacy_token_studio_redirect(request: Request, username: str, path_slug: str):
    return RedirectResponse("/token-factory/", status_code=302)

"""Board picker HTML — root ``/``."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.middleware import require_user
from infrastructure import deps
from domains.boards import services as svc_boards

router = APIRouter()


def _boards_list_response(request: Request, ctx: dict) -> HTMLResponse:
    """HTML for the picker; mark non-cacheable so lists stay fresh after renames, etc."""
    resp = request.app.state.templates.TemplateResponse(
        request, "boards_index.html", ctx
    )
    resp.headers["Cache-Control"] = "private, no-store, must-revalidate"
    return resp


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    user = require_user(request)
    boards = svc_boards.list_boards(user.id)
    if not boards:
        ctx = deps.editorial_template_context(None, request)
        ctx.update({"boards": [], "has_any_board": False})
        return _boards_list_response(request, ctx)

    if len(boards) == 1:
        base = deps.canonical_board_base_path(boards[0].id)
        return RedirectResponse(f"{base}/", status_code=303)

    ctx = deps.editorial_template_context(None, request)
    ctx.update({"boards": boards, "has_any_board": True})
    return _boards_list_response(request, ctx)

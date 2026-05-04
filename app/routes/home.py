"""Board picker home page and board CRUD JSON endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import auth
from boardfactory import boards as bf_boards
from routes import deps
from services import boards as svc_boards

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
    user = auth.require_user(request)
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


@router.post("/api/boards")
async def api_create_board(
    request: Request,
    board_id: str = Form(...),
    project_name: str | None = Form(default=None),
):
    user = auth.require_user(request)
    bid = bf_boards.slugify(board_id)
    try:
        summary = svc_boards.create_board(
            bid,
            owner_user_id=user.id,
            project_name=project_name or board_id,
        )
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardExists:
        raise HTTPException(409, f"Board {bid!r} already exists")
    base = deps.canonical_board_base_path(summary.id)
    return JSONResponse({"id": summary.id, "url": f"{base}/"})


@router.delete("/api/boards/{board_id}")
def api_delete_board(request: Request, board_id: str):
    user = auth.require_user(request)
    try:
        svc_boards.delete_board(user.id, board_id)
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Unknown board")
    return JSONResponse({"deleted": board_id})

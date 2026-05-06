"""Board list JSON — create/delete boards."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth.middleware import require_user
from boardfactory import boards as bf_boards
from infrastructure import deps
from domains.boards import services as svc_boards

router = APIRouter()


class CloneBoardBody(BaseModel):
    path_slug: str | None = None
    project_name: str | None = None


@router.post("/api/boards")
async def api_create_board(
    request: Request,
    board_id: str = Form(...),
    project_name: str | None = Form(default=None),
):
    user = require_user(request)
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


@router.post("/api/boards/{board_id}/clone")
async def api_clone_board(
    request: Request,
    board_id: str,
    body: CloneBoardBody | None = None,
):
    user = require_user(request)
    payload = body or CloneBoardBody()
    try:
        summary = svc_boards.clone_board(
            user.id,
            board_id,
            path_slug=payload.path_slug,
            project_name=payload.project_name,
        )
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Unknown board")
    except svc_boards.BoardExists as e:
        raise HTTPException(409, str(e))
    base = deps.canonical_board_base_path(summary.id)
    return JSONResponse({"id": summary.id, "url": f"{base}/"}, status_code=201)


@router.delete("/api/boards/{board_id}")
def api_delete_board(request: Request, board_id: str):
    user = require_user(request)
    try:
        svc_boards.delete_board(user.id, board_id)
    except svc_boards.InvalidBoardId:
        raise HTTPException(400, "Invalid board id")
    except svc_boards.BoardNotFound:
        raise HTTPException(404, "Unknown board")
    return JSONResponse({"deleted": board_id})

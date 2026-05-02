"""Serve workspace files and mockup PNGs for an owned board."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from routes import deps
from storage.fs import workspace as fs_ws

router = APIRouter()


@router.get("/b/{board_id}/asset/{rest:path}")
def asset(request: Request, board_id: str, rest: str):
    deps.ensure_owned_board(request, board_id)
    target = deps.workspace_file_or_404(board_id, rest)
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})


@router.get("/b/{board_id}/mockup/{name}")
def mockup(request: Request, board_id: str, name: str):
    deps.ensure_owned_board(request, board_id)
    mockup_dir = (fs_ws.board_root(board_id) / "mockup").resolve()
    target = (mockup_dir / name).resolve()
    if not str(target).startswith(str(mockup_dir)):
        raise HTTPException(400, "Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)

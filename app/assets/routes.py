"""Serve workspace files and mockup PNGs for an owned board."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from routes import deps
from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws

router = APIRouter()

NestedBoardId = Annotated[str, Depends(deps.require_nested_board)]


def _serve(board_id: str, rel: str, *, no_store: bool = False) -> Response:
    """Stream a board-relative file via the configured ``BoardStore``.

    Local backend: ``FileResponse`` (sendfile, zero-copy).
    Remote backend: 302 to a presigned URL when supported, else inline
    ``Response(bytes)``.
    """
    store = bs.get_store()
    if not store.exists(board_id, rel):
        raise HTTPException(404)
    signed = store.signed_get_url(board_id, rel)
    if signed:
        return RedirectResponse(signed, status_code=302)
    if isinstance(store, bs.LocalBoardStore):
        headers = {"Cache-Control": "no-store"} if no_store else {}
        return FileResponse(store.local_path(board_id, rel), headers=headers)
    headers = {"Cache-Control": "no-store"} if no_store else {}
    return Response(content=store.read_bytes(board_id, rel), headers=headers)


@router.get("/users/{username}/board-games/{path_slug}/asset/{rest:path}")
def asset_nested(request: Request, board_id: NestedBoardId, rest: str):
    try:
        fs_ws.safe_workspace_relative(board_id, rest)
    except fs_ws.PathTraversalError:
        raise HTTPException(400, "Invalid path")
    return _serve(board_id, f"workspace/{rest}", no_store=True)


@router.get("/b/{board_id}/asset/{rest:path}")
def asset_legacy(request: Request, board_id: str, rest: str):
    deps.ensure_owned_board(request, board_id)
    try:
        fs_ws.safe_workspace_relative(board_id, rest)
    except fs_ws.PathTraversalError:
        raise HTTPException(400, "Invalid path")
    return _serve(board_id, f"workspace/{rest}", no_store=True)


@router.get("/users/{username}/board-games/{path_slug}/mockup/{name}")
def mockup_nested(request: Request, board_id: NestedBoardId, name: str):
    if "/" in name or ".." in name or name.startswith("."):
        raise HTTPException(400, "Invalid path")
    return _serve(board_id, f"mockup/{name}")


@router.get("/b/{board_id}/mockup/{name}")
def mockup_legacy(request: Request, board_id: str, name: str):
    deps.ensure_owned_board(request, board_id)
    if "/" in name or ".." in name or name.startswith("."):
        raise HTTPException(400, "Invalid path")
    return _serve(board_id, f"mockup/{name}")

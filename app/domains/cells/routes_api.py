"""HTTP routes for the cells domain under ``/users/.../board-games/...``.

  * GET    – read the side-panel payload for one cell
  * PATCH  – update mutable per-cell metadata (currently `space_kind`)
  * POST   – promote a history file to live for one cell
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from boardfactory import config as bf_config

from domains.cells import repository as cells_repo
from infrastructure import deps

router = APIRouter()

NestedBoardId = Annotated[str, Depends(deps.require_nested_board)]


# ── GET ───────────────────────────────────────────────────────────────


@router.get("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}")
def api_cell(request: Request, board_id: NestedBoardId, category: str, asset_id: str):
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


# ── PATCH ─────────────────────────────────────────────────────────────


async def _api_patch_cell(
    request: Request, board_id: str, category: str, asset_id: str,
) -> JSONResponse:
    if category != "spaces":
        raise HTTPException(400, "Only perimeter spaces support PATCH metadata.")
    body = await request.json()
    space_kind = body.get("space_kind")
    if space_kind not in ("standard", "event"):
        raise HTTPException(
            400,
            'JSON body must include "space_kind": "standard" or "event"',
        )
    if not cells_repo.update_space_kind(board_id, asset_id, space_kind):
        raise HTTPException(404, f"Unknown space design: {asset_id}")
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.patch("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}")
async def api_patch_cell_nested(
    request: Request, board_id: NestedBoardId, category: str, asset_id: str,
):
    return await _api_patch_cell(request, board_id, category, asset_id)


# ── POST promote ──────────────────────────────────────────────────────


def _api_cell_promote(
    request: Request, board_id: str, category: str, asset_id: str, filename: str,
) -> JSONResponse:
    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets  # noqa: PLC0415
        try:
            bf_assets.promote(category, asset_id, filename)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
    return JSONResponse(deps.build_cell_side_panel_payload(board_id, category, asset_id))


@router.post("/users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}/promote")
def api_cell_promote_nested(
    request: Request, board_id: NestedBoardId, category: str, asset_id: str,
    filename: str = Form(...),
):
    return _api_cell_promote(request, board_id, category, asset_id, filename)

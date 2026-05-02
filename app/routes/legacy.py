"""Top-level redirects kept for old bookmarks and external links."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import auth
from services import boards as svc_boards

router = APIRouter()


@router.get("/spec")
def legacy_spec(request: Request):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(f"/b/{bid}/spec" if bid else "/", status_code=301)


@router.get("/preview")
def legacy_preview(request: Request):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(f"/b/{bid}/preview" if bid else "/", status_code=301)


@router.get("/setup")
def legacy_setup(request: Request):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(f"/b/{bid}/setup" if bid else "/", status_code=301)


@router.get("/spaces")
def legacy_spaces(request: Request):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(f"/b/{bid}/" if bid else "/", status_code=301)


@router.get("/panels/{panel_id}")
def legacy_panel(request: Request, panel_id: str):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(f"/b/{bid}/#panels:{panel_id}" if bid else "/", status_code=301)


@router.get("/centerpiece")
def legacy_centerpiece(request: Request):
    user = auth.require_user(request)
    bid = svc_boards.default_board_id_for_user(user.id)
    return RedirectResponse(
        f"/b/{bid}/#centerpiece:centerpiece" if bid else "/", status_code=301
    )

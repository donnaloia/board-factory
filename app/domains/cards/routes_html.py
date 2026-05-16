"""Card Factory HTML routes — deck picker and deck detail pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.middleware import require_user
from jobs import cost_ledger
from domains.cards import repository as cards_repo
from domains.cards import services as svc_cards

router = APIRouter()


# ────────────────────────── deck picker / list ──────────────────────────


@router.get("/card-factory/", response_class=HTMLResponse)
def card_factory_index(request: Request):
    user = require_user(request)
    decks_raw = svc_cards.list_decks(user.id)
    username = user.public_dict()["username"]
    decks = []
    for d in decks_raw:
        prefix = f"/users/{username}/card-factory/{d.path_slug}"
        previews = svc_cards.live_preview_urls_for_deck_index(
            d.id, prefix, max_urls=6
        )
        decks.append(
            {
                "path_slug": d.path_slug,
                "project_name": d.project_name,
                "status": d.status,
                "slot_count": d.slot_count,
                "hero_url": previews[0] if previews else None,
                "scatter_urls": previews[1:6][:5],
            }
        )

    ctx = {
        "board_id": None,
        "board_base": None,
        "project": "Card Factory",
        "has_palette": False,
        "cost": cost_ledger.summary(),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict(),
        "decks": decks,
    }
    resp = request.app.state.templates.TemplateResponse(
        request, "card_factory_index.html", ctx
    )
    resp.headers["Cache-Control"] = "private, no-store, must-revalidate"
    return resp


# ────────────────────────── deck detail ──────────────────────────


@router.get(
    "/users/{username}/card-factory/{path_slug}/", response_class=HTMLResponse
)
def card_factory_detail(request: Request, username: str, path_slug: str):
    user = require_user(request)
    if user.username != username:
        return RedirectResponse("/card-factory/", status_code=303)

    rows = cards_repo.list_decks_for_user(user.id)
    deck_row = next((r for r in rows if r.path_slug == path_slug), None)
    if deck_row is None:
        return RedirectResponse("/card-factory/", status_code=303)

    deck_id = deck_row.id
    prefix = f"/users/{username}/card-factory/{path_slug}"

    payload = svc_cards.build_deck_payload(deck_id, deck_http_prefix=prefix)

    # Load user's boards for the link-board picker
    from domains.boards import services as svc_boards
    boards = svc_boards.list_boards(user.id)

    ctx = {
        "board_id": None,
        "board_base": None,
        "project": deck_row.project_name or "Card Factory",
        "has_palette": False,
        "cost": cost_ledger.summary(),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict(),
        "deck": payload,
        "deck_prefix": prefix,
        "boards": boards,
    }
    return request.app.state.templates.TemplateResponse(
        request, "card_factory_detail.html", ctx
    )

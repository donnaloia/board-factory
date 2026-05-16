"""Card Factory JSON/binary routes."""

from __future__ import annotations

import functools
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from auth.middleware import require_user
from infrastructure import deps
from domains.cards import repository as cards_repo
from domains.cards import services as svc_cards
from domains.cards import workspace as deck_ws
from domains.cards import pipeline_jobs

router = APIRouter()


# ────────────────────────── helpers ──────────────────────────


def _deck_http_prefix(deck_id: str, request: Request) -> str:
    """URL prefix for this deck's routes, derived from the deck row."""
    row = cards_repo.get_deck(deck_id)
    if row is None:
        raise HTTPException(404, "Deck not found")
    from auth.models import UserRecord
    from infrastructure.db import session_scope

    with session_scope() as session:
        user = session.get(UserRecord, row.owner_user_id)
    if user is None:
        raise HTTPException(404, "Deck owner not found")
    return f"/users/{user.username}/card-factory/{row.path_slug}"


def _require_deck(deck_id: str, user_id: str):
    row = cards_repo.get_deck(deck_id)
    if row is None or row.owner_user_id != user_id:
        raise HTTPException(404, "Deck not found")
    return row


def _resolve_deck_id(username: str, path_slug: str, request: Request) -> str:
    """Resolve (username, path_slug) → deck_id, enforcing ownership."""
    user = require_user(request)
    if user.username != username:
        raise HTTPException(404, "Not found")
    rows = cards_repo.list_decks_for_user(user.id)
    for r in rows:
        if r.path_slug == path_slug:
            return r.id
    raise HTTPException(404, "Deck not found")


# ────────────────────────── deck CRUD ──────────────────────────


class CreateDeckBody(BaseModel):
    path_slug: str
    project_name: str = ""
    slot_count: int = 6


@router.post("/api/card-factory/decks")
async def api_create_deck(request: Request, body: CreateDeckBody):
    user = require_user(request)
    try:
        summary = svc_cards.create_deck(
            user.id,
            body.path_slug,
            body.project_name or body.path_slug,
            body.slot_count,
        )
    except svc_cards.InvalidDeckId as e:
        raise HTTPException(400, str(e))
    except svc_cards.DeckExists as e:
        raise HTTPException(409, str(e))
    prefix = f"/users/{user.username}/card-factory/{summary.path_slug}"
    return JSONResponse({"id": summary.id, "url": f"{prefix}/"}, status_code=201)


@router.delete("/users/{username}/card-factory/{path_slug}")
def api_delete_deck(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    try:
        svc_cards.delete_deck(user.id, deck_id)
    except svc_cards.DeckNotFound:
        raise HTTPException(404, "Deck not found")
    return JSONResponse({"deleted": deck_id})


class PatchDeckBody(BaseModel):
    project_name: str


@router.patch("/users/{username}/card-factory/{path_slug}/api/deck")
async def api_patch_deck(
    request: Request, username: str, path_slug: str, body: PatchDeckBody
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    try:
        name = svc_cards.rename_deck(user.id, deck_id, body.project_name)
    except svc_cards.DeckNotFound:
        raise HTTPException(404, "Deck not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"ok": True, "project_name": name})


# ────────────────────────── board linking ──────────────────────────


class LinkBoardBody(BaseModel):
    board_id: str


@router.post("/users/{username}/card-factory/{path_slug}/api/link-board")
async def api_link_board(
    request: Request, username: str, path_slug: str, body: LinkBoardBody
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    try:
        svc_cards.link_board(user.id, deck_id, body.board_id)
    except svc_cards.BoardAuthError as e:
        raise HTTPException(403, str(e))
    except svc_cards.DeckNotFound:
        raise HTTPException(404, "Deck not found")
    return JSONResponse({"ok": True})


# ────────────────────────── derive prompts ──────────────────────────


@router.post("/users/{username}/card-factory/{path_slug}/api/derive-prompts")
async def api_derive_prompts(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    deck = _require_deck(deck_id, user.id)

    keys = deps.user_provider_api_keys(request)
    openai_key = keys.get("openai_key", "")

    worker = functools.partial(
        pipeline_jobs.derive_prompts_job,
        deck_id=deck_id,
        board_id=deck.linked_board_id,
        openai_key=openai_key,
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Derive prompts for {deck.project_name}",
        operation="card_derive_prompts",
        target=deck_id,
        cost_estimate=pipeline_jobs.DERIVE_PROMPTS_COST_USD,
        fn=worker,
    )
    return JSONResponse({"job_id": job_id})


# ────────────────────────── frame gate ──────────────────────────


@router.post("/users/{username}/card-factory/{path_slug}/api/generate-frames")
async def api_generate_frames(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    deck = _require_deck(deck_id, user.id)

    try:
        svc_cards.assert_board_linked(deck)
        svc_cards.assert_has_style(deck)
    except svc_cards.FrameGateError as e:
        raise HTTPException(422, str(e))

    keys = deps.user_provider_api_keys(request)
    openai_key = keys.get("openai_key", "")

    worker = functools.partial(
        pipeline_jobs.generate_frames_job,
        deck_id=deck_id,
        openai_key=openai_key,
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Generate frames for {deck.project_name}",
        operation="card_generate_frames",
        target=deck_id,
        cost_estimate=pipeline_jobs.GENERATE_FRAMES_COST_USD,
        fn=worker,
    )
    return JSONResponse({"job_id": job_id})


@router.get("/users/{username}/card-factory/{path_slug}/api/frame-candidates")
def api_list_frame_candidates(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    deck = _require_deck(deck_id, user.id)
    prefix = _deck_http_prefix(deck_id, request)
    candidates = cards_repo.list_all_frame_candidates(deck_id)
    return JSONResponse({
        "candidates": [
            {
                "id": c.id,
                "candidate_index": c.candidate_index,
                "job_id": c.job_id,
                "image_url": f"{prefix}/api/card-frame-candidates/{c.id}/image",
                "inner_rect": c.inner_rect_json,
                "created_ms": c.created_ms,
            }
            for c in candidates
        ]
    })


@router.get(
    "/users/{username}/card-factory/{path_slug}"
    "/api/card-frame-candidates/{candidate_id}/image"
)
def api_frame_candidate_image(
    request: Request,
    username: str,
    path_slug: str,
    candidate_id: int,
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    candidate = cards_repo.get_frame_candidate(candidate_id)
    if candidate is None or candidate.deck_id != deck_id:
        raise HTTPException(404, "Candidate not found")
    img_path = deck_ws.deck_root(deck_id) / candidate.rel_path
    if not img_path.exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(str(img_path), media_type="image/png")


class CommitFrameBody(BaseModel):
    candidate_id: int


@router.post("/users/{username}/card-factory/{path_slug}/api/commit-frame")
async def api_commit_frame(
    request: Request, username: str, path_slug: str, body: CommitFrameBody
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    try:
        svc_cards.commit_frame(user.id, deck_id, body.candidate_id)
    except svc_cards.FrameGateError as e:
        raise HTTPException(422, str(e))
    return JSONResponse({"ok": True, "committed_frame_id": body.candidate_id})


# ────────────────────────── card generation ──────────────────────────


class GenerateCardsBody(BaseModel):
    slot_indices: list[int] | None = None  # None means all slots


@router.post("/users/{username}/card-factory/{path_slug}/api/generate-cards")
async def api_generate_cards(
    request: Request, username: str, path_slug: str, body: GenerateCardsBody | None = None
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    deck = _require_deck(deck_id, user.id)

    try:
        svc_cards.assert_frame_committed(deck)
    except svc_cards.FrameGateError as e:
        raise HTTPException(422, str(e))

    slot_indices = (body.slot_indices if body and body.slot_indices is not None
                    else list(range(deck.slot_count)))

    keys = deps.user_provider_api_keys(request)
    openai_key = keys.get("openai_key", "")

    worker = functools.partial(
        pipeline_jobs.generate_cards_job,
        deck_id=deck_id,
        slot_indices=slot_indices,
        openai_key=openai_key,
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Generate cards for {deck.project_name}",
        operation="card_generate_cards",
        target=deck_id,
        cost_estimate=pipeline_jobs.GENERATE_CARDS_COST_USD_PER_SLOT * len(slot_indices),
        fn=worker,
    )
    return JSONResponse({"job_id": job_id})


@router.get("/users/{username}/card-factory/{path_slug}/api/cards")
def api_list_cards(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    prefix = _deck_http_prefix(deck_id, request)
    slots = cards_repo.list_slots(deck_id)
    return JSONResponse({
        "slots": [
            {
                "slot_index": s.slot_index,
                "title": s.title,
                "illustration_prompt": s.illustration_prompt,
                "stat_lines": s.stat_lines_json or [],
                "prompt_source": s.prompt_source,
                "live_url": (
                    f"{prefix}/api/cards/{s.slot_index}/live" if s.live_rel_path else None
                ),
            }
            for s in slots
        ]
    })


@router.get("/users/{username}/card-factory/{path_slug}/api/cards/{slot_index}/live")
def api_card_live_image(
    request: Request, username: str, path_slug: str, slot_index: int
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    slot = cards_repo.get_slot(deck_id, slot_index)
    if slot is None or not slot.live_rel_path:
        raise HTTPException(404, "No live card image yet")
    img_path = deck_ws.deck_root(deck_id) / slot.live_rel_path
    if not img_path.exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(str(img_path), media_type="image/png")


class UpdateSlotBody(BaseModel):
    title: str | None = None
    illustration_prompt: str | None = None
    stat_lines: list[str] | None = None


@router.patch("/users/{username}/card-factory/{path_slug}/api/cards/{slot_index}")
async def api_update_slot(
    request: Request,
    username: str,
    path_slug: str,
    slot_index: int,
    body: UpdateSlotBody,
):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    payload = {"slot_index": slot_index, "prompt_source": "user"}
    if body.title is not None:
        payload["title"] = body.title
    if body.illustration_prompt is not None:
        payload["illustration_prompt"] = body.illustration_prompt
    if body.stat_lines is not None:
        payload["stat_lines"] = body.stat_lines
    cards_repo.bulk_update_slot_prompts(deck_id, [payload])
    return JSONResponse({"ok": True})


# ────────────────────────── deck payload ──────────────────────────


@router.get("/users/{username}/card-factory/{path_slug}/api/payload")
def api_deck_payload(request: Request, username: str, path_slug: str):
    user = require_user(request)
    deck_id = _resolve_deck_id(username, path_slug, request)
    _require_deck(deck_id, user.id)
    prefix = _deck_http_prefix(deck_id, request)
    return JSONResponse(svc_cards.build_deck_payload(deck_id, deck_http_prefix=prefix))

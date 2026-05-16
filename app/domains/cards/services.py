"""Card Factory service layer — business logic and gate enforcement.

Each public function is a short, top-down chain of named calls so the
high-level flow is readable at a glance. Non-trivial work is factored into
private helpers below the public surface.

Gate invariants (fail-fast, no silent fallbacks):
  ``assert_board_linked``  — required before frame generation.
  ``assert_has_style``     — required before frame generation.
  ``assert_frame_committed`` — required before card generation.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from dataclasses import dataclass

from domains.cards import repository as cards_repo
from domains.cards import workspace as deck_ws
from domains.cards.models import CardDeckRecord


# ────────────────────────── exceptions ──────────────────────────


class DeckNotFound(LookupError):
    pass


class InvalidDeckId(ValueError):
    pass


class DeckExists(ValueError):
    pass


class FrameGateError(RuntimeError):
    """Raised when a pre-condition for an operation is not met."""


class BoardAuthError(PermissionError):
    """Raised when the user does not own the requested board."""


# ────────────────────────── value types ──────────────────────────


@dataclass
class DeckSummary:
    id: str
    path_slug: str
    project_name: str
    status: str
    slot_count: int
    linked_board_id: str | None
    committed_frame_id: int | None
    created_ms: int


# ────────────────────────── helpers ──────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,126}[a-z0-9]$")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise InvalidDeckId(
            "Deck path slug must be 3–128 lowercase alphanumeric or hyphen characters."
        )


def _summary(row: CardDeckRecord) -> DeckSummary:
    return DeckSummary(
        id=row.id,
        path_slug=row.path_slug,
        project_name=row.project_name,
        status=row.status,
        slot_count=row.slot_count,
        linked_board_id=row.linked_board_id,
        committed_frame_id=row.committed_frame_id,
        created_ms=row.created_ms,
    )


def _load_deck_or_raise(deck_id: str) -> CardDeckRecord:
    row = cards_repo.get_deck(deck_id)
    if row is None:
        raise DeckNotFound(f"Deck {deck_id!r} not found")
    return row


# ────────────────────────── gate assertions ──────────────────────────


def assert_board_linked(deck: CardDeckRecord) -> None:
    if not deck.linked_board_id:
        raise FrameGateError("Link a source board game before generating frames.")


def assert_has_style(deck: CardDeckRecord) -> None:
    if not deck.style_prompt and not deck.palette_json:
        raise FrameGateError(
            "No style information — link a board that has completed a style-lock analysis."
        )


def assert_frame_committed(deck: CardDeckRecord) -> None:
    if deck.committed_frame_id is None:
        raise FrameGateError(
            "Complete the frame gate first: generate frame candidates and commit one."
        )


# ────────────────────────── CRUD ──────────────────────────


def create_deck(
    user_id: str,
    path_slug: str,
    project_name: str,
    slot_count: int = 6,
) -> DeckSummary:
    _validate_slug(path_slug)
    existing = cards_repo.list_decks_for_user(user_id)
    if any(d.path_slug == path_slug for d in existing):
        raise DeckExists(f"You already have a deck with slug {path_slug!r}.")
    row = cards_repo.create_deck(
        owner_user_id=user_id,
        path_slug=path_slug,
        project_name=project_name or path_slug,
        slot_count=slot_count,
    )
    deck_ws.create_deck_skeleton(row.id)
    cards_repo.ensure_slot_rows(row.id, slot_count)
    return _summary(row)


def list_decks(user_id: str) -> list[DeckSummary]:
    return [_summary(r) for r in cards_repo.list_decks_for_user(user_id)]


def get_deck_or_raise(deck_id: str) -> CardDeckRecord:
    return _load_deck_or_raise(deck_id)


def delete_deck(user_id: str, deck_id: str) -> None:
    deck = _load_deck_or_raise(deck_id)
    if deck.owner_user_id != user_id:
        raise DeckNotFound(f"Deck {deck_id!r} not found")
    cards_repo.delete_deck(deck_id)
    deck_ws.delete_deck_workspace(deck_id)


# ────────────────────────── board linking ──────────────────────────


def rename_deck(user_id: str, deck_id: str, project_name: str) -> str:
    """Update display title / card-set name. Returns the trimmed name stored."""
    deck = _load_deck_or_raise(deck_id)
    if deck.owner_user_id != user_id:
        raise DeckNotFound(f"Deck {deck_id!r} not found")
    name = project_name.strip()
    if not name:
        raise ValueError("Deck title cannot be empty.")
    if len(name) > 512:
        raise ValueError("Deck title must be 512 characters or fewer.")
    cards_repo.set_deck_project_name(deck_id, name)
    return name


def link_board(user_id: str, deck_id: str, board_id: str) -> None:
    """Copy style + generation parameters from ``board_id`` into the deck.

    Enforces that the user owns the source board.
    """
    deck = _load_deck_or_raise(deck_id)
    if deck.owner_user_id != user_id:
        raise DeckNotFound(f"Deck {deck_id!r} not found")

    _assert_user_owns_board(user_id, board_id)

    style_prompt, palette_json, provider, openai_model, openai_quality = (
        _read_board_style(board_id)
    )

    cards_repo.set_deck_linked_board(
        deck_id,
        board_id=board_id,
        style_prompt=style_prompt,
        palette_json=palette_json,
        provider=provider,
        openai_model=openai_model,
        openai_quality=openai_quality,
    )


def _assert_user_owns_board(user_id: str, board_id: str) -> None:
    from infrastructure.db import session_scope
    from domains.boards.models import OwnedBoardRecord

    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_id)
    if row is None or row.user_id != user_id:
        raise BoardAuthError(f"You do not own board {board_id!r}.")


def _read_board_style(board_id: str) -> tuple[str, str | None, str, str, str]:
    """Return (style_prompt, palette_json, provider, openai_model, openai_quality)."""
    from domains.boards.models import BoardGameRecord
    from infrastructure.db import session_scope

    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
    if row is None:
        raise DeckNotFound(f"Source board {board_id!r} not found.")
    return (
        row.style_prompt or "",
        row.palette_json,
        row.provider or "openai",
        row.openai_model or "gpt-image-2",
        row.openai_quality or "low",
    )


# ────────────────────────── frame commit ──────────────────────────


def commit_frame(user_id: str, deck_id: str, candidate_id: int) -> None:
    """Commit one frame candidate as the active frame for the deck.

    Copies the candidate PNG to ``frames/committed/frame.png`` and writes
    the inner rect JSON.  Transitions deck status to ``card_pending``.
    """
    deck = _load_deck_or_raise(deck_id)
    if deck.owner_user_id != user_id:
        raise DeckNotFound(f"Deck {deck_id!r} not found")

    candidate = cards_repo.get_frame_candidate(candidate_id)
    if candidate is None or candidate.deck_id != deck_id:
        raise FrameGateError(f"Frame candidate {candidate_id} not found for this deck.")

    _copy_candidate_to_committed(deck_id, candidate)
    cards_repo.set_deck_committed_frame(deck_id, candidate_id)


def _copy_candidate_to_committed(deck_id: str, candidate) -> None:
    import shutil

    src = deck_ws.deck_root(deck_id) / candidate.rel_path
    dst = deck_ws.committed_frame_path(deck_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    deck_ws.write_committed_inner_rect(deck_id, dict(candidate.inner_rect_json))


# ────────────────────────── cost estimates ──────────────────────────


def estimate_frame_cost_usd() -> float:
    from domains.cards.pipeline_jobs import GENERATE_FRAMES_COST_USD
    return GENERATE_FRAMES_COST_USD


def estimate_card_cost_usd(slot_count: int) -> float:
    from domains.cards.pipeline_jobs import GENERATE_CARDS_COST_USD_PER_SLOT
    return GENERATE_CARDS_COST_USD_PER_SLOT * slot_count


def estimate_derive_prompts_cost_usd() -> float:
    from domains.cards.pipeline_jobs import DERIVE_PROMPTS_COST_USD
    return DERIVE_PROMPTS_COST_USD


# ────────────────────────── payload builders ──────────────────────────


def live_preview_urls_for_deck_index(
    deck_id: str,
    deck_http_prefix: str,
    *,
    max_urls: int = 6,
) -> list[str]:
    """Ordered live card image URLs for deck picker thumbnails (slot_index order)."""
    slots = cards_repo.list_slots(deck_id)
    live_slots = sorted(
        [s for s in slots if s.live_rel_path],
        key=lambda s: s.slot_index,
    )
    out: list[str] = []
    for s in live_slots[:max_urls]:
        out.append(f"{deck_http_prefix}/api/cards/{s.slot_index}/live")
    return out


def build_deck_payload(deck_id: str, *, deck_http_prefix: str) -> dict:
    """Full JSON payload for the deck detail view."""
    deck = _load_deck_or_raise(deck_id)
    slots = cards_repo.list_slots(deck_id)
    candidates = cards_repo.list_all_frame_candidates(deck_id)

    return {
        "deck_id": deck_id,
        "path_slug": deck.path_slug,
        "project_name": deck.project_name,
        "status": deck.status,
        "slot_count": deck.slot_count,
        "layout_template_id": deck.layout_template_id,
        "linked_board_id": deck.linked_board_id,
        "committed_frame_id": deck.committed_frame_id,
        "style_prompt": deck.style_prompt,
        "has_palette": bool(deck.palette_json),
        "frame_candidates": [_candidate_view(c, deck_http_prefix) for c in candidates],
        "slots": [_slot_view(s, deck_http_prefix, deck_id) for s in slots],
        "estimates": {
            "frames_usd": estimate_frame_cost_usd(),
            "cards_usd": estimate_card_cost_usd(deck.slot_count),
            "derive_prompts_usd": estimate_derive_prompts_cost_usd(),
        },
    }


def _candidate_view(candidate, prefix: str) -> dict:
    return {
        "id": candidate.id,
        "candidate_index": candidate.candidate_index,
        "job_id": candidate.job_id,
        "image_url": f"{prefix}/api/card-frame-candidates/{candidate.id}/image",
        "inner_rect": candidate.inner_rect_json,
        "created_ms": candidate.created_ms,
    }


def _slot_view(slot, prefix: str, deck_id: str) -> dict:
    live_url = (
        f"{prefix}/api/cards/{slot.slot_index}/live"
        if slot.live_rel_path
        else None
    )
    return {
        "id": slot.id,
        "slot_index": slot.slot_index,
        "title": slot.title,
        "illustration_prompt": slot.illustration_prompt,
        "stat_lines": slot.stat_lines_json or [],
        "prompt_source": slot.prompt_source,
        "live_url": live_url,
        "live_frame_commit_id": slot.live_frame_commit_id,
    }

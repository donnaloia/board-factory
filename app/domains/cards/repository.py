"""DB I/O for the cards domain.

Pure data layer: opens its own ``session_scope``, never touches disk or HTTP.
Callers in ``cards.services`` route through here — never import ORM models
directly from routes.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Iterable

from sqlalchemy import select

from infrastructure.db import session_scope
from domains.cards.models import CardDeckRecord, CardFrameCandidateRecord, CardSlotRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


# ────────────────────────── decks ──────────────────────────


def create_deck(
    *,
    owner_user_id: str,
    path_slug: str,
    project_name: str,
    slot_count: int = 6,
) -> CardDeckRecord:
    now = _now_ms()
    with session_scope() as session:
        row = CardDeckRecord(
            id=str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            path_slug=path_slug,
            project_name=project_name,
            slot_count=slot_count,
            status="draft",
            created_ms=now,
            updated_ms=now,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def get_deck(deck_id: str) -> CardDeckRecord | None:
    with session_scope() as session:
        return session.get(CardDeckRecord, deck_id)


def list_decks_for_user(user_id: str) -> list[CardDeckRecord]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(CardDeckRecord)
                .where(CardDeckRecord.owner_user_id == user_id)
                .order_by(CardDeckRecord.created_ms.desc())
            )
        )


def delete_deck(deck_id: str) -> None:
    with session_scope() as session:
        row = session.get(CardDeckRecord, deck_id)
        if row is not None:
            session.delete(row)


def set_deck_project_name(deck_id: str, project_name: str) -> None:
    with session_scope() as session:
        row = session.get(CardDeckRecord, deck_id)
        if row is not None:
            row.project_name = project_name
            row.updated_ms = _now_ms()


def set_deck_linked_board(
    deck_id: str,
    *,
    board_id: str,
    style_prompt: str,
    palette_json: str | None,
    provider: str,
    openai_model: str,
    openai_quality: str,
) -> None:
    """Copy style + generation parameters from a board into the deck."""
    with session_scope() as session:
        row = session.get(CardDeckRecord, deck_id)
        if row is None:
            return
        row.linked_board_id = board_id
        row.style_prompt = style_prompt
        row.palette_json = palette_json
        row.provider = provider
        row.openai_model = openai_model
        row.openai_quality = openai_quality
        row.status = "frame_pending"
        row.updated_ms = _now_ms()


def set_deck_status(deck_id: str, status: str) -> None:
    with session_scope() as session:
        row = session.get(CardDeckRecord, deck_id)
        if row is not None:
            row.status = status
            row.updated_ms = _now_ms()


def set_deck_committed_frame(deck_id: str, candidate_id: int) -> None:
    with session_scope() as session:
        row = session.get(CardDeckRecord, deck_id)
        if row is not None:
            row.committed_frame_id = candidate_id
            row.status = "card_pending"
            row.updated_ms = _now_ms()


# ────────────────────────── frame candidates ──────────────────────────


def insert_frame_candidate(
    *,
    deck_id: str,
    job_id: str,
    candidate_index: int,
    rel_path: str,
    inner_rect: dict,
    m_chrome_paint_hash: str | None,
    provider: str,
    model_id: str,
) -> CardFrameCandidateRecord:
    now = _now_ms()
    with session_scope() as session:
        row = CardFrameCandidateRecord(
            deck_id=deck_id,
            job_id=job_id,
            candidate_index=candidate_index,
            rel_path=rel_path,
            inner_rect_json=inner_rect,
            m_chrome_paint_hash=m_chrome_paint_hash,
            provider=provider,
            model_id=model_id,
            created_ms=now,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def get_frame_candidate(candidate_id: int) -> CardFrameCandidateRecord | None:
    with session_scope() as session:
        return session.get(CardFrameCandidateRecord, candidate_id)


def list_frame_candidates(deck_id: str, job_id: str) -> list[CardFrameCandidateRecord]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(CardFrameCandidateRecord)
                .where(
                    CardFrameCandidateRecord.deck_id == deck_id,
                    CardFrameCandidateRecord.job_id == job_id,
                )
                .order_by(CardFrameCandidateRecord.candidate_index)
            )
        )


def list_all_frame_candidates(deck_id: str) -> list[CardFrameCandidateRecord]:
    """All candidates ever generated for this deck, newest job first."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(CardFrameCandidateRecord)
                .where(CardFrameCandidateRecord.deck_id == deck_id)
                .order_by(
                    CardFrameCandidateRecord.created_ms.desc(),
                    CardFrameCandidateRecord.candidate_index,
                )
            )
        )


# ────────────────────────── card slots ──────────────────────────


def ensure_slot_rows(deck_id: str, count: int) -> None:
    """Upsert exactly ``count`` slot rows for ``deck_id``.

    Adds missing rows (with empty prompts); does not delete extras if
    count shrinks (callers should avoid shrinking slot_count).
    """
    now = _now_ms()
    with session_scope() as session:
        existing = {
            r.slot_index
            for r in session.scalars(
                select(CardSlotRecord).where(CardSlotRecord.deck_id == deck_id)
            )
        }
        for i in range(count):
            if i not in existing:
                session.add(
                    CardSlotRecord(
                        deck_id=deck_id,
                        slot_index=i,
                        created_ms=now,
                        updated_ms=now,
                    )
                )


def get_slot(deck_id: str, slot_index: int) -> CardSlotRecord | None:
    with session_scope() as session:
        return session.scalar(
            select(CardSlotRecord).where(
                CardSlotRecord.deck_id == deck_id,
                CardSlotRecord.slot_index == slot_index,
            )
        )


def list_slots(deck_id: str) -> list[CardSlotRecord]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(CardSlotRecord)
                .where(CardSlotRecord.deck_id == deck_id)
                .order_by(CardSlotRecord.slot_index)
            )
        )


def bulk_update_slot_prompts(
    deck_id: str,
    payloads: Iterable[dict],
) -> None:
    """Write agent-derived prompts for multiple slots at once.

    Each dict in ``payloads`` must contain ``slot_index``, and may contain
    any of: ``title``, ``illustration_prompt``, ``stat_lines`` (list[str]).
    """
    now = _now_ms()
    with session_scope() as session:
        for p in payloads:
            idx = p["slot_index"]
            row = session.scalar(
                select(CardSlotRecord).where(
                    CardSlotRecord.deck_id == deck_id,
                    CardSlotRecord.slot_index == idx,
                )
            )
            if row is None:
                continue
            if "title" in p:
                row.title = p["title"]
            if "illustration_prompt" in p:
                row.illustration_prompt = p["illustration_prompt"]
            if "stat_lines" in p:
                row.stat_lines_json = p["stat_lines"]
            row.prompt_source = p.get("prompt_source", "agent")
            row.updated_ms = now


def set_slot_live(
    deck_id: str,
    slot_index: int,
    *,
    live_rel_path: str,
    live_frame_commit_id: int | None,
) -> None:
    now = _now_ms()
    with session_scope() as session:
        row = session.scalar(
            select(CardSlotRecord).where(
                CardSlotRecord.deck_id == deck_id,
                CardSlotRecord.slot_index == slot_index,
            )
        )
        if row is not None:
            row.live_rel_path = live_rel_path
            row.live_frame_commit_id = live_frame_commit_id
            row.updated_ms = now

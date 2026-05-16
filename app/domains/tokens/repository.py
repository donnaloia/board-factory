"""DB I/O for the tokens domain.

Pure data layer: opens its own ``session_scope``, never touches disk or HTTP.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select

from infrastructure.db import session_scope
from domains.tokens.models import TokenRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_token(
    *,
    owner_user_id: str,
    path_slug: str,
    slug: str,
    display_name: str,
    linked_board_id: str | None = None,
    locomotion_profile: str = "walk",
    facing_policy: str = "flip_x",
    canvas_w: int = 96,
    canvas_h: int = 128,
    frame_fps: int = 12,
) -> TokenRecord:
    now = _now_ms()
    with session_scope() as session:
        row = TokenRecord(
            id=str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            linked_board_id=linked_board_id,
            path_slug=path_slug,
            slug=slug,
            display_name=display_name,
            locomotion_profile=locomotion_profile,
            facing_policy=facing_policy,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            frame_fps=frame_fps,
            design_locked=False,
            live_run_id=None,
            created_ms=now,
            updated_ms=now,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return row


def get_token(token_id: str) -> TokenRecord | None:
    with session_scope() as session:
        return session.get(TokenRecord, token_id)


def get_token_by_path(owner_user_id: str, path_slug: str) -> TokenRecord | None:
    with session_scope() as session:
        return session.scalar(
            select(TokenRecord).where(
                TokenRecord.owner_user_id == owner_user_id,
                TokenRecord.path_slug == path_slug,
            )
        )


def list_tokens_for_user(owner_user_id: str) -> list[TokenRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(TokenRecord)
            .where(TokenRecord.owner_user_id == owner_user_id)
            .order_by(TokenRecord.created_ms)
        ).all()
        return list(rows)


def delete_token(token_id: str) -> bool:
    with session_scope() as session:
        row = session.get(TokenRecord, token_id)
        if row is None:
            return False
        session.delete(row)
        return True


# ── narrow setters ────────────────────────────────────────────────────────────

def set_design_locked(token_id: str, locked: bool) -> None:
    with session_scope() as session:
        row = session.get(TokenRecord, token_id)
        if row is None:
            raise LookupError(f"TokenRecord {token_id!r} not found")
        row.design_locked = locked
        row.updated_ms = _now_ms()


def set_live_run_id(token_id: str, run_id: str) -> None:
    with session_scope() as session:
        row = session.get(TokenRecord, token_id)
        if row is None:
            raise LookupError(f"TokenRecord {token_id!r} not found")
        row.live_run_id = run_id
        row.updated_ms = _now_ms()


def set_display_name(token_id: str, display_name: str) -> None:
    with session_scope() as session:
        row = session.get(TokenRecord, token_id)
        if row is None:
            raise LookupError(f"TokenRecord {token_id!r} not found")
        row.display_name = display_name
        row.updated_ms = _now_ms()


def set_linked_board(token_id: str, linked_board_id: str | None) -> None:
    """Re-associate (or clear) the source board for palette/style seeding."""
    with session_scope() as session:
        row = session.get(TokenRecord, token_id)
        if row is None:
            raise LookupError(f"TokenRecord {token_id!r} not found")
        row.linked_board_id = linked_board_id
        row.updated_ms = _now_ms()

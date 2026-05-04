"""Which user owns which board directory (slug)."""

from __future__ import annotations

import time

from boardfactory import boards as bf_boards
from sqlalchemy import func, select

from storage.db import session_scope
from models.core import OwnedBoardRecord, UserRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


def require_nonblank_user_id(user_id: str, *, field: str = "user_id") -> None:
    """``owned_boards.user_id`` is NOT NULL; boards are never created without an owner."""
    if not user_id:
        raise ValueError(f"{field} is required and cannot be empty.")


def path_slug_in_use(user_id: str, slug: str) -> bool:
    with session_scope() as session:
        row = session.scalar(
            select(OwnedBoardRecord).where(
                OwnedBoardRecord.user_id == user_id,
                OwnedBoardRecord.path_slug == slug,
            )
        )
    return row is not None


def user_owns_board(user_id: str, board_id: str) -> bool:
    if not user_id:
        return False
    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_id)
        return row is not None and row.user_id == user_id


def link_board_to_user(
    board_id: str,
    user_id: str,
    *,
    path_slug: str | None = None,
) -> None:
    require_nonblank_user_id(user_id)
    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_id)
        if row is None:
            ps = path_slug if path_slug is not None else board_id
            session.add(
                OwnedBoardRecord(
                    board_uuid=board_id,
                    user_id=user_id,
                    path_slug=ps,
                    created_ms=_now_ms(),
                    list_order=0,
                )
            )
        else:
            row.user_id = user_id
            row.created_ms = _now_ms()
            if path_slug is not None:
                row.path_slug = path_slug


def path_slug_for_board(board_id: str) -> str | None:
    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_id)
        return row.path_slug if row else None


def list_board_ids_for_user(user_id: str) -> list[str]:
    with session_scope() as session:
        rows = session.scalars(
            select(OwnedBoardRecord.board_uuid).where(OwnedBoardRecord.user_id == user_id)
        ).all()
    return list(rows)


def assign_all_unowned_disk_boards_to_user(user_id: str) -> None:
    """Attach ownership of every on-disk board that has no ``owned_boards`` row yet."""
    require_nonblank_user_id(user_id)
    from boardfactory import boards as bf_boards
    from services import board_definition as bd

    for info in bf_boards.list_boards():
        with session_scope() as session:
            if session.get(OwnedBoardRecord, info.id) is not None:
                continue
        if bd.load_catalog_dict(info.id) is None:
            bd.persist_catalog_dict(
                info.id,
                bf_boards.default_catalog_dict(info.id, info.project),
            )
        link_board_to_user(info.id, user_id, path_slug=info.id)


def backfill_owned_boards_if_empty() -> None:
    """If ``owned_boards`` is empty but users exist, assign every on-disk board to the oldest user.

    Used when the SQLite file was deleted or not yet created (empty DB after
    migrations). Normal clones use a committed ``.boardfactory.db`` at the repo root that
    already contains ownership rows.
    """
    with session_scope() as session:
        n = session.scalar(select(func.count()).select_from(OwnedBoardRecord)) or 0
        if int(n) > 0:
            return
        first = session.scalars(select(UserRecord).order_by(UserRecord.created_ms.asc())).first()
        if first is None:
            return
    assign_all_unowned_disk_boards_to_user(first.id)

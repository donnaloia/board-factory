"""DB I/O for the boards domain.

Pure data layer: opens its own ``session_scope``, reads/writes
``board_games`` and ``owned_boards``. Callers in ``boards.services`` and
elsewhere route through this — never touch the ORM directly from a route.

This module also resolves on-disk board roots, because that resolution
is itself a DB query (``owned_boards`` → ``user_id`` → on-disk path).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from sqlalchemy import select

from infrastructure.db import session_scope
from models.core import BoardGameRecord, OwnedBoardRecord


# ────────────────────────── path resolution ──────────────────────────


class BoardNotFound(LookupError):
    """Raised when ``board_uuid`` is not present in ``owned_boards``."""


def _boards_dir() -> Path:
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "."))
    return repo / "data" / "boards"


def owner_user_id_for_board(board_uuid: str) -> str | None:
    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_uuid)
        return row.user_id if row else None


def store_board_root(board_uuid: str) -> Path:
    """Return ``<boards>/<user_id>/<board_uuid>/`` for the owning user.

    Raises ``BoardNotFound`` if no ``owned_boards`` row exists. Existence of
    the directory itself is *not* checked here: callers that need an existing
    skeleton should call ``BoardStore.create_board_skeleton``.
    """
    with session_scope() as session:
        row = session.get(OwnedBoardRecord, board_uuid)
        user_id = row.user_id if row else None

    if not user_id:
        raise BoardNotFound(board_uuid)
    return _boards_dir() / user_id / board_uuid


# ────────────────────────── ownership reads ──────────────────────────


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


# ────────────────────────── ownership writes ──────────────────────────


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


# ────────────────────────── board_games reads ──────────────────────────


def board_exists(board_id: str) -> bool:
    with session_scope() as session:
        return session.get(BoardGameRecord, board_id) is not None

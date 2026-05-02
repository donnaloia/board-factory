"""Board-level use cases.

Wraps ``boardfactory.boards`` (which still owns the on-disk skeleton) and
the ``storage.fs`` helpers so routes get a stable, FastAPI-agnostic API.

Errors:
  * ``BoardNotFound``  - not owned by this user, or (for ``get_board`` /
    ``rename_board``) no board directory on disk
  * ``InvalidBoardId`` - id violates the slug rules
  * ``BoardExists``    - id collides with an existing board directory
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from boardfactory import boards as bf_boards
from sqlalchemy import delete

from services import board_definition as bd
from services import board_ownership as board_own
from services import catalog as svc_catalog
from storage.db import session_scope
from storage.fs import workspace as fs_ws
from storage.models.core import (
    AssetVersionRecord,
    BoardCatalogRecord,
    BoardGameRecord,
    OwnedBoardRecord,
)


class BoardNotFound(LookupError):
    pass


class InvalidBoardId(ValueError):
    pass


class BoardExists(ValueError):
    pass


@dataclass(frozen=True)
class BoardSummary:
    """UI-friendly view of a board.

    ``has_palette`` / ``has_mockup`` reflect on-disk state at call time;
    ``project`` / ``has_catalog`` come from the relational catalog when present.
    """

    id: str
    project: str
    has_catalog: bool
    has_mockup: bool
    has_palette: bool


def _summary(info: bf_boards.BoardInfo) -> BoardSummary:
    d = bd.load_catalog_dict(info.id)
    if d is not None:
        return BoardSummary(
            id=info.id,
            project=str(d.get("project") or info.id),
            has_catalog=True,
            has_mockup=info.has_mockup,
            has_palette=fs_ws.has_palette(info.id),
        )
    return BoardSummary(
        id=info.id,
        project=info.project,
        has_catalog=info.has_catalog,
        has_mockup=info.has_mockup,
        has_palette=fs_ws.has_palette(info.id),
    )


def list_boards(user_id: str) -> list[BoardSummary]:
    allowed = set(board_own.list_board_ids_for_user(user_id))
    out: list[BoardSummary] = []
    for b in bf_boards.list_boards():
        if b.id in allowed:
            out.append(_summary(b))
    return out


def default_board_id_for_user(user_id: str) -> str | None:
    """If this user owns exactly one board, return its id (for legacy redirects)."""
    rows = list_boards(user_id)
    if len(rows) == 1:
        return rows[0].id
    return None


def get_board(user_id: str, board_id: str) -> BoardSummary:
    if not bf_boards.is_valid_id(board_id):
        raise InvalidBoardId(board_id)
    if not board_own.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)
    info = bf_boards.get_board(board_id)
    if info is None:
        raise BoardNotFound(board_id)
    return _summary(info)


def create_board(board_id: str, *, owner_user_id: str, project_name: str | None = None) -> BoardSummary:
    """Create a new empty board and record ``owner_user_id`` as its owner."""
    board_own.require_nonblank_user_id(owner_user_id, field="owner_user_id")
    if not bf_boards.is_valid_id(board_id):
        raise InvalidBoardId(board_id)
    if bf_boards.get_board(board_id) is not None:
        raise BoardExists(board_id)
    pname = project_name or board_id
    bf_boards.create_board(board_id, project_name=pname)
    bd.persist_catalog_dict(board_id, bf_boards.default_catalog_dict(board_id, pname))
    board_own.link_board_to_user(board_id, owner_user_id)
    info = bf_boards.get_board(board_id)
    assert info is not None
    return _summary(info)


def delete_board(user_id: str, board_id: str) -> None:
    """Remove a board's Postgres rows (spec, asset index, ownership) and delete
    ``boards/<id>/`` from disk when present.
    """
    if not bf_boards.is_valid_id(board_id):
        raise InvalidBoardId(board_id)
    if not board_own.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)

    with session_scope() as session:
        session.execute(
            delete(AssetVersionRecord).where(AssetVersionRecord.board_id == board_id)
        )
        session.execute(
            delete(BoardCatalogRecord).where(BoardCatalogRecord.board_id == board_id)
        )
        session.execute(delete(OwnedBoardRecord).where(OwnedBoardRecord.board_id == board_id))
        session.execute(delete(BoardGameRecord).where(BoardGameRecord.board_id == board_id))

    root = fs_ws.board_root(board_id)
    if root.exists():
        shutil.rmtree(root)


def rename_board(user_id: str, board_id: str, project_name: str) -> BoardSummary:
    """Update the display name (catalog.project)."""
    if not bf_boards.is_valid_id(board_id):
        raise InvalidBoardId(board_id)
    if not board_own.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)
    new_name = (project_name or "").strip()
    if not new_name:
        raise ValueError("Project name cannot be empty")
    data = svc_catalog.load_catalog(board_id)
    data["project"] = new_name
    svc_catalog.save_catalog(board_id, data)
    info = bf_boards.get_board(board_id)
    if info is None:
        raise BoardNotFound(board_id)
    return _summary(info)


def mockup_present(board_id: str) -> tuple[bool, str]:
    """Return ``(exists, board-relative-path)`` for templates."""
    catalog = svc_catalog.safe_load_catalog(board_id)
    if catalog is None:
        return (False, "mockup/board.png")
    rel = fs_ws.mockup_relpath(catalog)
    return ((fs_ws.board_root(board_id) / rel).exists(), rel)

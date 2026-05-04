"""Board-level use cases.

Wraps ``boardfactory.boards`` (which still owns the on-disk skeleton) and
the ``storage.fs`` helpers so routes get a stable, FastAPI-agnostic API.

Errors:
  * ``BoardNotFound``  - not owned by this user, or (for ``get_board`` /
    ``rename_board``) no board directory on disk
  * ``InvalidBoardId`` - board key is not a UUID string
  * ``BoardExists``    - chosen URL slug is already used by this owner
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from sqlalchemy import delete

from services import board_definition as bd
from services import board_ownership as board_own
from services import catalog as svc_catalog
from storage import board_store as bs
from storage.db import session_scope
from storage.fs import workspace as fs_ws
from models.core import (
    AssetVersionRecord,
    BoardGameRecord,
    OwnedBoardRecord,
)


class BoardNotFound(LookupError):
    pass


class InvalidBoardId(ValueError):
    pass


class BoardExists(ValueError):
    pass


# Compositor writes ``board_idle.png`` (and ``board_active.png``); older trees may
# have ``board_preview.png`` only — prefer idle first for list + preview page URLs.
COMPOSITE_PREVIEW_CANDIDATES: tuple[str, ...] = (
    "workspace/preview/board_idle.png",
    "workspace/preview/board_preview.png",
)


def composite_preview_workspace_rel(board_id: str) -> str | None:
    """First composited preview PNG on disk, or ``None``."""
    store = bs.get_store()
    for rel in COMPOSITE_PREVIEW_CANDIDATES:
        if store.exists(board_id, rel):
            return rel
    return None


def _mockup_thumb_name(board_id: str, catalog: dict | None) -> str | None:
    """Basename for ``/mockup/{name}`` when that file exists; else ``None``."""
    store = bs.get_store()
    rel = fs_ws.mockup_relpath(catalog)
    if not store.exists(board_id, rel):
        return None
    return Path(rel).name


@dataclass(frozen=True)
class BoardSummary:
    """UI-friendly view of a board.

    ``has_palette`` / ``has_mockup`` reflect on-disk state at call time;
    ``project`` / ``has_catalog`` come from the relational catalog when present.
    ``has_board_preview`` is true when a composited preview PNG exists
    (``board_idle.png`` or legacy ``board_preview.png``).
    ``board_preview_asset_rest`` is the path under ``workspace/`` for the asset
    URL (e.g. ``preview/board_idle.png``).
    ``mockup_thumb_name`` is the mockup filename for list thumbnails when present
    (used when there is no board preview).
    """

    id: str
    project: str
    path_slug: str  # URL segment under board-games/ (per-user unique)
    has_catalog: bool
    has_mockup: bool
    has_palette: bool
    has_board_preview: bool
    board_preview_asset_rest: str | None
    mockup_thumb_name: str | None


def _board_info_for_list(board_id: str) -> bf_boards.BoardInfo:
    """Prefer on-disk ``BoardInfo``; if the directory is missing (e.g. DB id
    renamed before the folder), synthesize a minimal row so owned boards still
    appear in the list — catalog/thumbnails may still resolve from the DB.
    """
    info = bf_boards.get_board(board_id)
    if info is not None:
        return info
    root = bf_config.board_root(board_id)
    d = bd.load_catalog_dict(board_id)
    project = str(d.get("project") or board_id) if d is not None else board_id
    return bf_boards.BoardInfo(
        id=board_id,
        project=project,
        catalog_path=root / "catalog.yml",
        has_catalog=False,
        has_mockup=False,
    )


def _summary(info: bf_boards.BoardInfo) -> BoardSummary:
    ps = board_own.path_slug_for_board(info.id) or info.id
    preview_ws_rel = composite_preview_workspace_rel(info.id)
    has_preview = preview_ws_rel is not None
    preview_asset_rest = (
        preview_ws_rel.removeprefix("workspace/") if preview_ws_rel else None
    )
    d = bd.load_catalog_dict(info.id)
    mock_name = _mockup_thumb_name(info.id, d)
    if d is not None:
        return BoardSummary(
            id=info.id,
            project=str(d.get("project") or info.id),
            path_slug=ps,
            has_catalog=True,
            has_mockup=info.has_mockup,
            has_palette=fs_ws.has_palette(info.id),
            has_board_preview=has_preview,
            board_preview_asset_rest=preview_asset_rest,
            mockup_thumb_name=mock_name,
        )
    return BoardSummary(
        id=info.id,
        project=info.project,
        path_slug=ps,
        has_catalog=info.has_catalog,
        has_mockup=info.has_mockup,
        has_palette=fs_ws.has_palette(info.id),
        has_board_preview=has_preview,
        board_preview_asset_rest=preview_asset_rest,
        mockup_thumb_name=mock_name,
    )


def _board_last_activity_ms(board_ids: list[str]) -> dict[str, int]:
    """Map ``board_id`` -> last-activity time for list ordering.

    Uses the later of ``board_games.updated_ms`` (catalog ``body_json`` saved)
    and ``style_lock_updated_ms`` (style-lock palette written to the row),
    in milliseconds. Boards with no row sort as 0 (last).
    """
    if not board_ids:
        return {}
    out: dict[str, int] = {}
    with session_scope() as session:
        for bid in board_ids:
            row = session.get(BoardGameRecord, bid)
            if row is None:
                out[bid] = 0
                continue
            cat = int(row.updated_ms)
            pal = int(row.style_lock_updated_ms) if row.style_lock_updated_ms is not None else 0
            out[bid] = max(cat, pal)
    return out


def list_boards(user_id: str) -> list[BoardSummary]:
    bids = board_own.list_board_ids_for_user(user_id)
    if not bids:
        return []
    updated_ms = _board_last_activity_ms(bids)
    summaries = [_summary(_board_info_for_list(bid)) for bid in bids]
    summaries.sort(key=lambda s: (-updated_ms.get(s.id, 0), s.id))
    return summaries


def default_board_id_for_user(user_id: str) -> str | None:
    """If this user owns exactly one board, return its id (for legacy redirects)."""
    rows = list_boards(user_id)
    if len(rows) == 1:
        return rows[0].id
    return None


def get_board(user_id: str, board_id: str) -> BoardSummary:
    if not bf_boards.is_board_uuid(board_id):
        raise InvalidBoardId(board_id)
    if not board_own.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)
    info = bf_boards.get_board(board_id)
    if info is None:
        raise BoardNotFound(board_id)
    return _summary(info)


def create_board(path_slug: str, *, owner_user_id: str, project_name: str | None = None) -> BoardSummary:
    """Create a new empty board and record ``owner_user_id`` as its owner."""
    board_own.require_nonblank_user_id(owner_user_id, field="owner_user_id")
    slug = bf_boards.slugify(path_slug)
    if not bf_boards.is_valid_id(slug):
        raise InvalidBoardId(slug)
    if board_own.path_slug_in_use(owner_user_id, slug):
        raise BoardExists(slug)
    bu = str(uuid.uuid4())
    pname = project_name or slug
    bd.persist_catalog_dict(bu, bf_boards.default_catalog_dict(bu, pname))
    board_own.link_board_to_user(bu, owner_user_id, path_slug=slug)
    bs.get_store().create_board_skeleton(bu)
    info = bf_boards.get_board(bu)
    if info is None:
        raise BoardNotFound(bu)
    return _summary(info)


def delete_board(user_id: str, board_id: str) -> None:
    """Remove a board's relational rows (spec, asset index, ownership) and
    delete its data tree from the configured ``BoardStore``.
    """
    if not bf_boards.is_board_uuid(board_id):
        raise InvalidBoardId(board_id)
    if not board_own.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)

    bs.get_store().delete_board(board_id)

    with session_scope() as session:
        session.execute(
            delete(AssetVersionRecord).where(AssetVersionRecord.board_uuid == board_id)
        )
        session.execute(delete(OwnedBoardRecord).where(OwnedBoardRecord.board_uuid == board_id))
        session.execute(delete(BoardGameRecord).where(BoardGameRecord.board_uuid == board_id))


def rename_board(user_id: str, board_id: str, project_name: str) -> BoardSummary:
    """Update the display name (catalog.project)."""
    if not bf_boards.is_board_uuid(board_id):
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
    return (bs.get_store().exists(board_id, rel), rel)

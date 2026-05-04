"""Resolve per-board storage paths under ``<boards-root>/<user_id>/<board_uuid>/``."""

from __future__ import annotations

import os
from pathlib import Path

from boardfactory import config as bf_config

from models.core import OwnedBoardRecord
from storage.db import session_scope


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
    """Absolute board root for app + pipeline when ownership is in the DB.

    Under each user, migration 0015 stores boards at ``<user_id>/<uuid>/``. Optional
    ``board_disk_map`` may alias the *basename* for new boards; if the map points
    elsewhere (common after UUID migration), we still prefer the real ``<uuid>/``
    folder when it exists so migrated trees are found.

    If the canonical path is missing, fall back to legacy flat dirs or disk-map
    targets.
    """
    boards_root = _boards_dir()
    sub = bf_config.physical_board_dir_name(board_uuid)

    with session_scope() as session:
        ob = session.get(OwnedBoardRecord, board_uuid)

    uid = ob.user_id if ob else None
    slug = ob.path_slug if ob else None

    if uid is None:
        return boards_root / sub

    # User-scoped: try migration layout first, then disk-map basename under user.
    for child_name in (board_uuid, sub):
        if not child_name:
            continue
        p = boards_root / uid / child_name
        if p.is_dir():
            return p

    if slug:
        flat_slug = boards_root / slug
        if flat_slug.is_dir():
            return flat_slug

    m = bf_config.board_disk_map()
    for key in (board_uuid, slug):
        if not key:
            continue
        for k, v in m.items():
            if str(k).lower() == key.lower():
                flat_mapped = boards_root / v
                if flat_mapped.is_dir():
                    return flat_mapped
                break

    # Default for mkdir: match migration (uuid folder) unless disk map renames it.
    if sub != board_uuid:
        return boards_root / uid / sub
    return boards_root / uid / board_uuid

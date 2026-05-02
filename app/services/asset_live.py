"""DB-backed resolution of which on-disk file is ``live`` for a cell."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from storage.db import session_scope
from storage.fs import workspace as fs_ws
from storage.models.core import AssetLiveRecord, AssetVersionRecord


def upsert_live_pointer(board_id: str, category: str, asset_id: str, live_rel_path: str) -> None:
    stamp = int(time.time() * 1000)
    stmt = sqlite_insert(AssetLiveRecord).values(
        board_id=board_id,
        category=category,
        asset_id=asset_id,
        live_rel_path=live_rel_path,
        updated_ms=stamp,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["board_id", "category", "asset_id"],
        set_={
            "live_rel_path": stmt.excluded.live_rel_path,
            "updated_ms": stmt.excluded.updated_ms,
        },
    )
    with session_scope() as session:
        session.execute(stmt)


def delete_live_pointer(board_id: str, category: str, asset_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(AssetLiveRecord).where(
                AssetLiveRecord.board_id == board_id,
                AssetLiveRecord.category == category,
                AssetLiveRecord.asset_id == asset_id,
            )
        )


def get_live_rel_path(board_id: str, category: str, asset_id: str) -> str | None:
    with session_scope() as session:
        row = session.scalar(
            select(AssetLiveRecord).where(
                AssetLiveRecord.board_id == board_id,
                AssetLiveRecord.category == category,
                AssetLiveRecord.asset_id == asset_id,
            )
        )
    return row.live_rel_path if row else None


def resolved_live_path(board_id: str, category: str, asset_id: str) -> Path:
    """Prefer ``asset_live``; fall back to the legacy ``live/...`` path."""
    ws = fs_ws.workspace_dir(board_id)
    rel = get_live_rel_path(board_id, category, asset_id)
    if rel:
        p = ws / rel
        if p.exists():
            return p
    return fs_ws.live_path(board_id, category, asset_id)


def migrate_live_pointers_from_disk(board_id: str) -> int:
    """Create ``asset_live`` rows from existing ``live/*.png`` when missing.

    Matches a live file to a history row by SHA-256 when possible; otherwise
    points at the ``live/...`` path so resolution still works.
    """
    ws = fs_ws.workspace_dir(board_id)
    live_root = ws / "live"
    if not live_root.exists():
        return 0
    updated = 0
    for png in live_root.rglob("*.png"):
        try:
            rel_live = png.relative_to(ws).as_posix()
        except ValueError:
            continue
        parts = Path(rel_live).parts
        if len(parts) < 3 or parts[0] != "live":
            continue
        if parts[1] == "centerpiece":
            category, asset_id = "centerpiece", "centerpiece"
        else:
            if len(parts) < 3:
                continue
            category = parts[1]
            fname = parts[2]
            if not fname.endswith(".png"):
                continue
            asset_id = fname[: -len(".png")]
        if get_live_rel_path(board_id, category, asset_id):
            continue
        try:
            digest = hashlib.sha256(png.read_bytes()).hexdigest()
        except OSError:
            digest = None
        target_rel = rel_live
        if digest:
            with session_scope() as session:
                row = session.scalar(
                    select(AssetVersionRecord)
                    .where(
                        AssetVersionRecord.board_id == board_id,
                        AssetVersionRecord.category == category,
                        AssetVersionRecord.asset_id == asset_id,
                        AssetVersionRecord.sha256 == digest,
                    )
                    .order_by(AssetVersionRecord.ts_ms.desc())
                )
            if row is not None:
                target_rel = row.rel_path
        upsert_live_pointer(board_id, category, asset_id, target_rel)
        updated += 1
    return updated


def migrate_live_pointers_for_catalog_boards() -> None:
    try:
        from boardfactory import boards as bf_boards
    except Exception:
        return
    for info in bf_boards.list_boards():
        if not info.has_catalog:
            continue
        try:
            migrate_live_pointers_from_disk(info.id)
        except Exception:
            continue

"""Persist asset history index rows + reconcile filesystem backfills."""

from __future__ import annotations

import hashlib
import time
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from storage import board_store as bs
from storage.db import session_scope
from models.core import AssetVersionRecord


def on_asset_event(kind: str, board_id: str, **kw: object) -> None:
    """Registered with ``boardfactory.assets`` — index new history rows in SQL."""
    if kind != "history_push":
        return
    basename = kw.get("basename")
    rel_path = kw.get("rel_path")
    category = kw.get("category")
    asset_id = kw.get("asset_id")
    ts_ms = kw.get("ts_ms")
    sha256 = kw.get("sha256")
    meta_json = kw.get("meta_json")
    if not isinstance(basename, str) or not isinstance(rel_path, str):
        return
    if not isinstance(category, str) or not isinstance(asset_id, str):
        return
    if not isinstance(ts_ms, int):
        ts_ms = int(time.time() * 1000)
    sh = sha256 if isinstance(sha256, str) else None
    mj = meta_json if isinstance(meta_json, str) else None
    _insert_version_row(
        board_id,
        category,
        asset_id,
        basename,
        rel_path,
        ts_ms,
        sh,
        mj,
    )


def _insert_version_row(
    board_id: str,
    category: str,
    asset_id: str,
    basename: str,
    rel_path: str,
    ts_ms: int,
    sha256_hex: str | None,
    meta_json: str | None,
) -> None:
    stmt = sqlite_insert(AssetVersionRecord).values(
        board_id=board_id,
        category=category,
        asset_id=asset_id,
        basename=basename,
        rel_path=rel_path,
        sha256=sha256_hex,
        ts_ms=ts_ms,
        meta_json=meta_json,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["board_id", "rel_path"])
    with session_scope() as session:
        session.execute(stmt)


def count_for_cell(board_id: str, category: str, asset_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AssetVersionRecord)
                .where(
                    AssetVersionRecord.board_id == board_id,
                    AssetVersionRecord.category == category,
                    AssetVersionRecord.asset_id == asset_id,
                )
            )
            or 0
        )


def backfill_board(board_id: str) -> int:
    """Scan ``workspace/history`` and insert missing index rows. Returns rows attempted."""
    store = bs.get_store()
    files = store.list(board_id, "workspace/history")
    if not files:
        return 0
    attempted = 0
    for full_rel in files:
        if not full_rel.endswith(".png"):
            continue
        attempted += 1
        # full_rel is e.g. "workspace/history/spaces/foo/<basename>.png"
        # Strip "workspace/" so the rel stored in the index matches the
        # convention used by push_to_history (workspace-relative).
        ws_rel = full_rel[len("workspace/"):]
        parts = PurePosixPath(ws_rel).parts
        if len(parts) < 4 or parts[0] != "history":
            continue
        category, asset_id = parts[1], parts[2]
        basename = parts[-1]
        try:
            raw = store.read_bytes(board_id, full_rel)
            digest = hashlib.sha256(raw).hexdigest()
        except (OSError, FileNotFoundError):
            digest = None
        try:
            ts_ms = store.stat(board_id, full_rel).mtime_ms
        except (OSError, FileNotFoundError):
            ts_ms = int(time.time() * 1000)
        meta_rel = full_rel[: -len(".png")] + ".meta.json"
        mj: str | None = None
        if store.exists(board_id, meta_rel):
            try:
                mj = store.read_bytes(board_id, meta_rel).decode("utf-8")
            except (OSError, UnicodeDecodeError):
                mj = None
        _insert_version_row(
            board_id, category, asset_id, basename, ws_rel, ts_ms, digest, mj,
        )
    return attempted


def backfill_all_boards_with_catalog() -> None:
    """Walk boards that have a catalog on disk and reconcile history indexes."""
    from boardfactory import boards as bf_boards

    for info in bf_boards.list_boards():
        if not info.has_catalog:
            continue
        try:
            backfill_board(info.id)
        except Exception:
            continue


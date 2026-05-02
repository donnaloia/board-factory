"""Persist asset history index rows + reconcile filesystem backfills."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from storage.db import session_scope
from storage.fs import workspace as fs_ws
from storage.models.core import AssetVersionRecord


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
    ws = fs_ws.workspace_dir(board_id)
    hist = ws / "history"
    if not hist.exists():
        return 0
    attempted = 0
    for png in hist.rglob("*.png"):
        attempted += 1
        try:
            rel = png.relative_to(ws).as_posix()
        except ValueError:
            continue
        parts = Path(rel).parts
        if len(parts) < 4 or parts[0] != "history":
            continue
        category, asset_id = parts[1], parts[2]
        basename = png.name
        try:
            raw = png.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
        except OSError:
            digest = None
        ts_ms = int(png.stat().st_mtime * 1000)
        meta_path = png.with_suffix(".meta.json")
        mj = None
        if meta_path.exists():
            try:
                mj = meta_path.read_text()
            except OSError:
                mj = None
        _insert_version_row(board_id, category, asset_id, basename, rel, ts_ms, digest, mj)
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


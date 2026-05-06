"""Pure DB I/O for the assets domain.

Two responsibilities, glued together because they hit the same single
table (``asset_versions``) and one writes what the other reads:

  * **Index history files** as rows in ``asset_versions`` — invoked from
    a pipeline event (:func:`on_asset_event`) on every history push, and
    also by :func:`backfill_board` for filesystem reconciliation.
  * **Read per-version metadata** back out of those rows
    (:func:`read_meta`).

Anything more ambitious than "select / insert one row" should live in
:mod:`assets.services` or higher; this module stays SQL-only.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from assets.models import AssetVersionRecord
from domains.boards.models import BoardGameRecord
from domains.cells.models import CellRecord


# ── pipeline event handler ────────────────────────────────────────────


def on_asset_event(kind: str, board_id: str, **kw: Any) -> None:
    """Registered with ``boardfactory.assets`` — index rows + live pointer updates."""
    if kind == "history_push":
        _on_history_push(board_id, kw)
    elif kind == "live_promote":
        _apply_live_promote(board_id, kw)


def _on_history_push(board_id: str, kw: dict[str, Any]) -> None:
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


def _apply_live_promote(board_id: str, kw: dict[str, Any]) -> None:
    category = kw.get("category")
    asset_id = kw.get("asset_id")
    history_filename = kw.get("history_filename")
    if not isinstance(category, str) or not isinstance(asset_id, str):
        return
    if not isinstance(history_filename, str):
        return
    rel = f"history/{category}/{asset_id}/{history_filename}"
    with session_scope() as session:
        av = session.scalar(
            select(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == board_id,
                AssetVersionRecord.rel_path == rel,
            )
        )
        if av is None:
            return
        cell = session.get(CellRecord, av.cell_id)
        if cell is None:
            return
        cell.live_asset_version_id = av.id


def prompt_from_asset_version_meta(meta_json: str | None) -> str | None:
    """Return stored prompt from ``asset_versions.meta_json`` when present."""
    if not meta_json:
        return None
    try:
        data = json.loads(meta_json)
    except Exception:
        return None
    if not isinstance(data, dict) or "prompt" not in data:
        return None
    p = data.get("prompt")
    if p is None:
        return None
    return str(p)


def merged_prompt_for_live_asset_row(
    board_id: str,
    category: str,
    asset_id: str,
    av: AssetVersionRecord,
) -> str | None:
    """Sidebar prompt for the history row referenced by ``cells.live_asset_version_id``.

    Uses ``meta_json`` first, then :func:`boardfactory.assets.read_meta` so legacy
    ``.meta.json`` sidecars still contribute when the DB row omits ``prompt``.
    """
    p = prompt_from_asset_version_meta(av.meta_json)
    if p is not None:
        return p
    from boardfactory import assets as bf_assets  # noqa: PLC0415
    from boardfactory import config as bf_config  # noqa: PLC0415

    with bf_config.set_active_board(board_id):
        meta = bf_assets.read_meta(category, asset_id, av.basename)
    if meta.get("prompt") is not None:
        return str(meta["prompt"])
    return None


# ── inserts ───────────────────────────────────────────────────────────


_CATEGORY_TO_KIND = {"spaces": "space", "panels": "panel", "centerpiece": "centerpiece"}


def _resolve_cell_id(session, board_id: str, category: str, asset_id: str) -> str | None:
    kind = _CATEGORY_TO_KIND.get(category)
    if kind is None:
        return None
    return session.scalar(
        select(CellRecord.id).where(
            CellRecord.board_uuid == board_id,
            CellRecord.kind == kind,
            CellRecord.slug == asset_id,
        )
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
    """Insert one history row, joining to ``cells`` by ``(category, asset_id)``.

    If no matching cell exists (orphan history file) we skip rather than
    fail — this can happen when a cell is renamed/deleted but its files
    weren't pruned. Pruning is a separate, deliberate operation.
    """
    with session_scope() as session:
        cell_id = _resolve_cell_id(session, board_id, category, asset_id)
        if cell_id is None:
            return
        stmt = pg_insert(AssetVersionRecord).values(
            board_uuid=board_id,
            cell_id=cell_id,
            category=category,
            asset_id=asset_id,
            basename=basename,
            rel_path=rel_path,
            sha256=sha256_hex,
            ts_ms=ts_ms,
            meta_json=meta_json,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["board_uuid", "rel_path"])
        session.execute(stmt)


# ── reads ─────────────────────────────────────────────────────────────


def count_for_cell(board_id: str, category: str, asset_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AssetVersionRecord)
                .where(
                    AssetVersionRecord.board_uuid == board_id,
                    AssetVersionRecord.category == category,
                    AssetVersionRecord.asset_id == asset_id,
                )
            )
            or 0
        )


def read_meta(board_id: str, category: str, asset_id: str, history_filename: str) -> dict | None:
    """Read ``meta_json`` for one history file as a dict, or ``None``.

    Lookup keys: ``(board_uuid, rel_path)``, where ``rel_path`` is the
    workspace-relative path the pipeline writes (``history/<cat>/<id>/<file>``).
    """
    rel = f"history/{category}/{asset_id}/{history_filename}"
    with session_scope() as session:
        row = session.scalar(
            select(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == board_id,
                AssetVersionRecord.rel_path == rel,
            )
        )
    if row is None or not row.meta_json:
        return None
    try:
        return json.loads(row.meta_json)
    except Exception:
        return None


# ── filesystem backfill ───────────────────────────────────────────────


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
    """Walk boards with a relational catalog row and reconcile history indexes."""
    from boardfactory import boards as bf_boards  # noqa: PLC0415

    for info in bf_boards.list_boards():
        with session_scope() as s:
            if s.get(BoardGameRecord, info.id) is None:
                continue
        try:
            backfill_board(info.id)
        except Exception:
            continue

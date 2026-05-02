"""Persist style-lock palette in ``board_games`` and materialize to disk for the pipeline."""

from __future__ import annotations

import time

from storage.db import session_scope
from storage.fs import workspace as fs_ws
from storage.models.core import BoardGameRecord


def persist_palette_from_style_dir(board_id: str) -> None:
    """Read ``workspace/style/palette.{json,gpl}`` into the relational row."""
    pj = fs_ws.palette_json_path(board_id)
    gpl = fs_ws.style_dir(board_id) / "palette.gpl"
    if not pj.exists():
        return
    try:
        jtext = pj.read_text()
    except OSError:
        return
    gpl_text = None
    if gpl.exists():
        try:
            gpl_text = gpl.read_text()
        except OSError:
            gpl_text = None
    stamp = int(time.time() * 1000)
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None:
            return
        row.palette_json = jtext
        row.palette_gpl_text = gpl_text
        row.style_lock_updated_ms = stamp


def materialize_palette_to_disk(board_id: str) -> bool:
    """If the DB holds palette JSON, write ``palette.json`` (and GPL when present)."""
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None or not row.palette_json:
            return False
        jtext = row.palette_json
        gpl_text = row.palette_gpl_text
    style = fs_ws.style_dir(board_id)
    style.mkdir(parents=True, exist_ok=True)
    fs_ws.palette_json_path(board_id).write_text(jtext)
    if gpl_text:
        (fs_ws.style_dir(board_id) / "palette.gpl").write_text(gpl_text)
    return True


def migrate_palette_from_disk_for_board(board_id: str) -> bool:
    """One-shot: copy on-disk palette into DB when the row has no palette yet."""
    pj = fs_ws.palette_json_path(board_id)
    if not pj.exists():
        return False
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None or row.palette_json:
            return False
    persist_palette_from_style_dir(board_id)
    return True


def migrate_palette_from_disk_all_boards() -> None:
    try:
        from boardfactory import boards as bf_boards
    except Exception:
        return
    for info in bf_boards.list_boards():
        if not info.has_catalog:
            continue
        try:
            migrate_palette_from_disk_for_board(info.id)
        except Exception:
            continue

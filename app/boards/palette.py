"""Persist style-lock palette in ``board_games`` and materialize to disk for the pipeline.

The pipeline writes ``workspace/style/palette.{json,gpl}`` after style
lock; the canonical copy lives in ``board_games.palette_json`` /
``palette_gpl_text`` so cross-board operations can read it without
walking disk. Materialize back to disk on board open / before pipeline
runs that expect the file in the workspace.
"""

from __future__ import annotations

import time

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from models.core import BoardGameRecord


_PALETTE_JSON_REL = "workspace/style/palette.json"
_PALETTE_GPL_REL = "workspace/style/palette.gpl"


def persist_palette_from_style_dir(board_id: str) -> None:
    """Read ``workspace/style/palette.{json,gpl}`` into the relational row."""
    store = bs.get_store()
    if not store.exists(board_id, _PALETTE_JSON_REL):
        return
    try:
        jtext = store.read_bytes(board_id, _PALETTE_JSON_REL).decode("utf-8")
    except OSError:
        return
    gpl_text: str | None = None
    if store.exists(board_id, _PALETTE_GPL_REL):
        try:
            gpl_text = store.read_bytes(board_id, _PALETTE_GPL_REL).decode("utf-8")
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
    store = bs.get_store()
    store.write_bytes(board_id, _PALETTE_JSON_REL, jtext.encode("utf-8"))
    if gpl_text:
        store.write_bytes(board_id, _PALETTE_GPL_REL, gpl_text.encode("utf-8"))
    return True


def migrate_palette_from_disk_for_board(board_id: str) -> bool:
    """One-shot: copy on-disk palette into DB when the row has no palette yet."""
    if not bs.get_store().exists(board_id, _PALETTE_JSON_REL):
        return False
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None or row.palette_json:
            return False
    persist_palette_from_style_dir(board_id)
    return True


def migrate_palette_from_disk_all_boards() -> None:
    try:
        from boardfactory import boards as bf_boards  # noqa: PLC0415
    except Exception:
        return
    for info in bf_boards.list_boards():
        with session_scope() as s:
            if s.get(BoardGameRecord, info.id) is None:
                continue
        try:
            migrate_palette_from_disk_for_board(info.id)
        except Exception:
            continue

"""Load ``workspace/meta/live_source`` records via ``BoardStore``.

Pipeline writes these JSON files from :func:`boardfactory.live_source.record_promoted_history_file`;
this module parses them for HTTP handlers so reads stay backend-agnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws


@dataclass(frozen=True)
class LiveSourceRecord:
    """Pointer written whenever ``promote()`` copies a history PNG to live."""

    history_filename: str
    recorded_ms: int
    schema: int = 1


def read_live_source(board_id: str, category: str, asset_id: str) -> LiveSourceRecord | None:
    """Return the promotion pointer for this cell, or ``None`` if missing / invalid."""
    rel = fs_ws.live_source_rel(category, asset_id)
    store = bs.get_store()
    if not store.exists(board_id, rel):
        return None
    try:
        raw = store.read_bytes(board_id, rel).decode("utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    fn = data.get("history_filename")
    if not isinstance(fn, str) or not fn.endswith(".png"):
        return None
    schema = data.get("schema", 1)
    if not isinstance(schema, int):
        return None
    rec_ms = data.get("recorded_ms", 0)
    if not isinstance(rec_ms, int):
        return None
    return LiveSourceRecord(
        history_filename=fn,
        recorded_ms=rec_ms,
        schema=schema,
    )

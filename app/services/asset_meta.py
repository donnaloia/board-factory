"""Read per-version metadata from ``asset_versions.meta_json``."""

from __future__ import annotations

import json

from sqlalchemy import select

from storage.db import session_scope
from models.core import AssetVersionRecord


def read_meta_from_db(board_id: str, category: str, asset_id: str, history_filename: str) -> dict | None:
    rel = f"history/{category}/{asset_id}/{history_filename}"
    with session_scope() as session:
        row = session.scalar(
            select(AssetVersionRecord).where(
                AssetVersionRecord.board_id == board_id,
                AssetVersionRecord.rel_path == rel,
            )
        )
    if row is None or not row.meta_json:
        return None
    try:
        return json.loads(row.meta_json)
    except Exception:
        return None

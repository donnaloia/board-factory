"""Relational board definition.

The board catalog (project, board_size, style, centerpiece, board_spaces,
feature_panels, frame, generation) is stored as a single Pydantic-validated
JSON blob in ``board_games.body_json``. The pipeline consumes a nested dict
or ``Catalog`` model built from that blob.

Style-lock palette state lives in dedicated columns on ``board_games``
because there's a separate writer (``services.workspace_palette``) that
materializes it to disk on job start.
"""

from __future__ import annotations

import time
from typing import Any

from boardfactory.schemas import Catalog

from storage.db import session_scope
from models.core import BoardGameRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_catalog_dict(board_id: str) -> dict[str, Any] | None:
    """Return a dict suitable for ``Catalog.model_validate``, or ``None``."""
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        if bg is None:
            return None
        return Catalog.model_validate_json(bg.body_json).model_dump(mode="python")


def persist_catalog_dict(board_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate ``data`` as a ``Catalog`` and persist as ``body_json``.

    Returns the validated model as a dict (JSON-friendly).
    """
    cat = Catalog.model_validate(data)
    body_json = cat.model_dump_json()
    stamp = _now_ms()

    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None:
            session.add(
                BoardGameRecord(
                    board_uuid=board_id,
                    body_json=body_json,
                    updated_ms=stamp,
                )
            )
        else:
            row.body_json = body_json
            row.updated_ms = stamp

    return cat.model_dump(mode="python")


def load_catalog_model(board_id: str) -> Catalog | None:
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        if bg is None:
            return None
        return Catalog.model_validate_json(bg.body_json)

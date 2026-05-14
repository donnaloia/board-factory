"""DB I/O for ``frame_instances`` rows.

Frames are the doc's "board-level fact" layer of the data model: one
adopted house frame per board, with provenance pointing back at the
source cell or asset version when the rim was extracted from existing
art. This module is the only place the ``frame_instances`` table is
written; ``app/domains/boards/routes_api.py`` calls these helpers from
the ``/api/frame/commit`` and ``/api/frame/disable`` handlers.

The on-disk pack at ``workspace/frames/house/`` remains the source of
truth for the actual rim pixels and masks. We keep both because:

  - the on-disk pack is what the compositor reads (no DB on the hot path)
  - the relational row is what the Atelier UI lists, what Approach D
    attaches its job to, and what enforces "one active frame per board"

When the runtime sees a board that has the on-disk pack but no DB row
(e.g. a board that adopted a frame before this migration shipped), the
``ensure_active_for_disk_pack`` helper backfills a row lazily on first
read, with ``model_id="legacy"``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select, update

from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from domains.spaces.models import FrameInstanceRecord
from infrastructure.db import session_scope


# ────────────────────────── plain-dict view ──────────────────────────


@dataclass(frozen=True)
class FrameInstanceView:
    """Read-side projection — never touched by SQLAlchemy after detach."""

    id: str
    board_uuid: str
    ring_px: int
    source_w: int
    source_h: int
    source_kind: str
    source_id: str | None
    source_cell_id: str | None
    source_asset_version_id: int | None
    model_id: str | None
    prompt_hash: str | None
    candidate_index: int | None
    notes: str
    active: bool
    created_ms: int

    @property
    def source_size(self) -> tuple[int, int]:
        return (self.source_w, self.source_h)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "board_uuid": self.board_uuid,
            "ring_px": self.ring_px,
            "source_size": [self.source_w, self.source_h],
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_cell_id": self.source_cell_id,
            "source_asset_version_id": self.source_asset_version_id,
            "model_id": self.model_id,
            "prompt_hash": self.prompt_hash,
            "candidate_index": self.candidate_index,
            "notes": self.notes,
            "active": self.active,
            "created_ms": self.created_ms,
        }


def _row_to_view(row: FrameInstanceRecord) -> FrameInstanceView:
    return FrameInstanceView(
        id=row.id,
        board_uuid=row.board_uuid,
        ring_px=row.ring_px,
        source_w=row.source_w,
        source_h=row.source_h,
        source_kind=row.source_kind,
        source_id=row.source_id,
        source_cell_id=row.source_cell_id,
        source_asset_version_id=row.source_asset_version_id,
        model_id=row.model_id,
        prompt_hash=row.prompt_hash,
        candidate_index=row.candidate_index,
        notes=row.notes or "",
        active=bool(row.active),
        created_ms=int(row.created_ms),
    )


# ────────────────────────── reads ──────────────────────────


def get_active(board_id: str) -> FrameInstanceView | None:
    """Return the currently-active FrameInstance for this board, or ``None``."""
    with session_scope() as session:
        row = session.scalar(
            select(FrameInstanceRecord).where(
                FrameInstanceRecord.board_uuid == board_id,
                FrameInstanceRecord.active.is_(True),
            )
        )
        if row is None:
            return None
        return _row_to_view(row)


def get_by_id(frame_id: str) -> FrameInstanceView | None:
    with session_scope() as session:
        row = session.get(FrameInstanceRecord, frame_id)
        if row is None:
            return None
        return _row_to_view(row)


def list_for_board(board_id: str, *, include_inactive: bool = False) -> list[FrameInstanceView]:
    with session_scope() as session:
        stmt = (
            select(FrameInstanceRecord)
            .where(FrameInstanceRecord.board_uuid == board_id)
            .order_by(FrameInstanceRecord.created_ms.desc())
        )
        if not include_inactive:
            stmt = stmt.where(FrameInstanceRecord.active.is_(True))
        rows = list(session.scalars(stmt))
        return [_row_to_view(r) for r in rows]


# ────────────────────────── writes ──────────────────────────


def replace_active(
    board_id: str,
    *,
    instance: bf_frames.FrameInstance,
    source_cell_id: str | None = None,
    source_asset_version_id: int | None = None,
) -> FrameInstanceView:
    """Mark every prior row for this board inactive, insert a new active row.

    Caller is responsible for having already written the on-disk pack
    (``adopt_house_frame``); this function only manages the DB row.
    """
    with session_scope() as session:
        session.execute(
            update(FrameInstanceRecord)
            .where(
                FrameInstanceRecord.board_uuid == board_id,
                FrameInstanceRecord.active.is_(True),
            )
            .values(active=False)
        )

        row = FrameInstanceRecord(
            board_uuid=board_id,
            ring_px=int(instance.ring_px),
            source_w=int(instance.source_size[0]),
            source_h=int(instance.source_size[1]),
            source_kind=instance.source_kind,
            source_id=instance.source_id,
            source_cell_id=source_cell_id or instance.source_cell_id,
            source_asset_version_id=(
                source_asset_version_id
                if source_asset_version_id is not None
                else instance.source_asset_version_id
            ),
            model_id=instance.model_id,
            prompt_hash=instance.prompt_hash,
            candidate_index=instance.candidate_index,
            notes=instance.notes or "",
            active=True,
            created_ms=int(instance.created_ms or time.time() * 1000),
        )
        session.add(row)
        session.flush()
        return _row_to_view(row)


def mark_all_inactive(board_id: str) -> int:
    """Used by ``/api/frame/disable`` — dropping the active flag without
    deleting the row preserves provenance ("the frame this board used to
    have"). Returns the number of rows touched."""
    with session_scope() as session:
        result = session.execute(
            update(FrameInstanceRecord)
            .where(
                FrameInstanceRecord.board_uuid == board_id,
                FrameInstanceRecord.active.is_(True),
            )
            .values(active=False)
        )
        return int(result.rowcount or 0)


# ────────────────────────── lazy backfill ──────────────────────────


def ensure_active_for_disk_pack(board_id: str) -> FrameInstanceView | None:
    """Adopt the on-disk pack into the DB if there is no active row yet.

    Lets boards that adopted a frame before this migration shipped pick
    up the new Atelier UX without a manual data migration. Returns the
    (possibly freshly-created) active row, or ``None`` when the board
    has no on-disk pack at all.
    """
    with bf_config.set_active_board(board_id):
        if not bf_frames.has_house_frame():
            return None
        existing = get_active(board_id)
        if existing is not None:
            return existing
        meta = bf_frames.read_house_meta()
        if meta is None:
            return None
        # Stamp legacy rows so the Atelier can show "imported from disk"
        # in the provenance panel.
        if not meta.model_id:
            meta.model_id = "legacy"
        return replace_active(board_id, instance=meta)

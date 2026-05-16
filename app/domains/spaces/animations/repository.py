"""DB I/O for ``space_animations`` rows.

Pure data layer: opens its own ``session_scope``. Touches ``BoardStore``
only to keep DB pointers and on-disk files in lock-step (e.g.
``delete_committed_animation`` unlinks the row's ``rel_path`` so we
don't strand bytes that nothing references). Callers are :mod:`services`
for orchestration; anything more ambitious than "select / insert one
row" belongs in ``services``.
"""

from __future__ import annotations

from sqlalchemy import select

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from domains.spaces.animations.models import SpaceAnimationRecord
from domains.spaces.models import CellRecord


def live_animations_by_panel_slug(board_id: str) -> dict[str, SpaceAnimationRecord]:
    """Committed live animations for functional panels on ``board_id``.

    Returns ``{panel_slug: SpaceAnimationRecord}`` for every functional
    cell on the board that has ``live_animation_id`` set. Used by the
    project export bundle (Godot handoff) to wire ``spaces[].assets.animation``.
    """
    with session_scope() as session:
        rows = session.execute(
            select(CellRecord.slug, SpaceAnimationRecord)
            .join(
                SpaceAnimationRecord,
                CellRecord.live_animation_id == SpaceAnimationRecord.id,
            )
            .where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "functional",
                CellRecord.live_animation_id.isnot(None),
            )
        ).all()
        out: dict[str, SpaceAnimationRecord] = {}
        for slug, record in rows:
            if not isinstance(slug, str) or record is None:
                continue
            session.expunge(record)
            out[slug] = record
        return out


def get_live_for_cell(cell_id: str) -> SpaceAnimationRecord | None:
    """Return the currently live animation for ``cell_id``, or ``None``."""
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        if cell is None or cell.live_animation_id is None:
            return None
        return session.get(SpaceAnimationRecord, cell.live_animation_id)


def get_by_id(animation_id: int) -> SpaceAnimationRecord | None:
    with session_scope() as session:
        return session.get(SpaceAnimationRecord, animation_id)


def list_history_for_cell(cell_id: str, limit: int = 50) -> list[SpaceAnimationRecord]:
    """All committed animations for ``cell_id``, newest first."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(SpaceAnimationRecord)
                .where(SpaceAnimationRecord.cell_id == cell_id)
                .order_by(SpaceAnimationRecord.created_ms.desc())
                .limit(limit)
            )
        )


def delete_committed_animation(animation_id: int) -> None:
    """Remove one ``space_animations`` row **and** its on-disk file.

    Deleting only the row would leave the GIF/APNG at ``rel_path`` as
    untracked bytes. We capture the row's ``board_uuid`` + ``rel_path``
    before deletion and unlink via the configured ``BoardStore``.

    ``cells.live_animation_id`` FK uses ``ON DELETE SET NULL``, so the
    cell pointer is cleared automatically as part of the row delete.
    File deletion is best-effort: if the file is already gone (e.g. the
    caller moved it out of band) the unlink is a no-op.
    """
    with session_scope() as session:
        row = session.get(SpaceAnimationRecord, animation_id)
        if row is None:
            return
        board_id = row.board_uuid
        rel_path = row.rel_path
        session.delete(row)

    bs.get_store().delete(board_id, rel_path)


def insert_committed_animation(
    *,
    board_uuid: str,
    cell_id: str,
    source_asset_version_id: int | None,
    rel_path: str,
    basename: str,
    encoding: str,
    fps: int,
    duration_ms: int,
    frame_count: int,
    provider: str,
    model_id: str,
    loop_strategy: str,
    sha256: str | None,
    proposal_manifest_rel_path: str | None,
    proposal_index: int | None,
    created_ms: int,
    notes: str = "",
) -> SpaceAnimationRecord:
    """Persist one row representing a newly-committed live animation.

    Returns the persisted record (with ``id`` populated). The caller is
    responsible for updating ``cells.live_animation_id`` separately so
    promotion is one explicit step (see :func:`set_cell_live_animation`).
    """
    with session_scope() as session:
        row = SpaceAnimationRecord(
            board_uuid=board_uuid,
            cell_id=cell_id,
            source_asset_version_id=source_asset_version_id,
            rel_path=rel_path,
            basename=basename,
            encoding=encoding,
            fps=fps,
            duration_ms=duration_ms,
            frame_count=frame_count,
            provider=provider,
            model_id=model_id,
            loop_strategy=loop_strategy,
            sha256=sha256,
            proposal_manifest_rel_path=proposal_manifest_rel_path,
            proposal_index=proposal_index,
            created_ms=created_ms,
            notes=notes,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def set_cell_live_animation(cell_id: str, animation_id: int | None) -> bool:
    """Point ``cells.live_animation_id`` at ``animation_id`` (or clear with ``None``).

    Returns ``True`` on success, ``False`` if the cell row is missing.
    """
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        if cell is None:
            return False
        cell.live_animation_id = animation_id
        return True

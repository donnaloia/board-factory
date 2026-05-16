"""DB I/O for ``cells`` rows.

Pure data layer: opens its own ``session_scope``, never touches HTTP or
Catalog (Pydantic). Callers are domain services that need cell-level
queries that ``board_definition`` doesn't already serve via the catalog
reassembly path.

If you find yourself querying ``cells`` directly from a route or another
domain, route the call through ``cells.services`` instead.

Disk-aware operations (``prune_cell_files``) live here because keeping
DB rows and on-disk files in lock-step is part of the cells repository's
contract — the audit invariant is that every byte under ``data/`` must
be reachable from a row, and vice versa.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import delete, func, select

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from domains.spaces.assets.models import AssetVersionRecord
from domains.spaces.animations.models import SpaceAnimationRecord
from domains.spaces.models import CellRecord


# ────────────────────────── id translation ──────────────────────────


_CATEGORY_TO_KIND = {"spaces": "perimeter", "panels": "functional", "centerpiece": "centerpiece"}
_KIND_TO_CATEGORY = {v: k for k, v in _CATEGORY_TO_KIND.items()}


def category_to_kind(category: str) -> str | None:
    """Map the legacy ``"spaces"|"panels"|"centerpiece"`` string used on
    URLs and the filesystem to the ``cells.kind`` enum value."""
    return _CATEGORY_TO_KIND.get(category)


def kind_to_category(kind: str) -> str | None:
    return _KIND_TO_CATEGORY.get(kind)


# ────────────────────────── reads ──────────────────────────


def find_id(board_id: str, category: str, slug: str) -> str | None:
    """Return ``cells.id`` for a (board, category, slug) triple, or None."""
    kind = category_to_kind(category)
    if kind is None:
        return None
    with session_scope() as session:
        return session.scalar(
            select(CellRecord.id).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )


def list_for_board(board_id: str) -> list[CellRecord]:
    with session_scope() as session:
        return list(session.scalars(
            select(CellRecord)
            .where(CellRecord.board_uuid == board_id)
            .order_by(CellRecord.kind, CellRecord.position_index)
        ))


def list_kind_slugs(board_id: str, kind: str) -> list[str]:
    """Just the slugs for one kind, sorted by ``position_index``."""
    with session_scope() as session:
        return list(session.scalars(
            select(CellRecord.slug)
            .where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
            )
            .order_by(CellRecord.position_index)
        ))


# ────────────────────────── focused mutators ──────────────────────────


def update_prompt(board_id: str, category: str, slug: str, prompt: str) -> bool:
    """Patch one cell's prompt. Returns True on success, False if not found."""
    kind = category_to_kind(category)
    if kind is None:
        return False
    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )
        if row is None:
            return False
        row.prompt = prompt
        return True


def bulk_update_prompts(
    board_id: str,
    updates: Iterable[tuple[str, str, str]],
) -> None:
    """Patch multiple cells' prompts in a single session.

    ``updates`` is an iterable of ``(kind, slug, prompt)`` triples where
    ``kind`` is the raw ``cells.kind`` value (``"perimeter"``,
    ``"functional"``, or ``"centerpiece"``). Silently skips unknowns.
    Opened in one ``session_scope`` so the caller pays one round-trip
    regardless of how many cells are updated.
    """
    rows_by_key: dict[tuple[str, str], CellRecord]
    with session_scope() as session:
        all_rows = session.scalars(
            select(CellRecord).where(CellRecord.board_uuid == board_id)
        ).all()
        rows_by_key = {(r.kind, r.slug): r for r in all_rows}
        for kind, slug, prompt in updates:
            row = rows_by_key.get((kind, slug))
            if row is not None:
                row.prompt = prompt


def update_space_kind(board_id: str, slug: str, space_kind: str) -> bool:
    """Patch a space cell's ``space_kind`` (``standard`` | ``event``)."""
    if space_kind not in ("standard", "event"):
        raise ValueError(f"invalid space_kind: {space_kind!r}")
    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "perimeter",
                CellRecord.slug == slug,
            )
        )
        if row is None:
            return False
        row.space_kind = space_kind
        return True


def patch_space_cell_metadata(
    board_id: str,
    slug: str,
    *,
    space_kind: str | None = None,
    update_space_kind: bool = False,
    triggers_functional_cell_id: str | None = None,
    update_triggers: bool = False,
) -> bool:
    """Patch ``space_kind`` and/or ``triggers_functional_cell_id`` on a space-design cell.

    Only fields with ``update_*`` True are written. For triggers, pass
    ``triggers_functional_cell_id=None`` with ``update_triggers=True`` to clear.
    Validates target row is ``kind='functional'`` on the same board when non-null.
    """
    if space_kind is not None and space_kind not in ("standard", "event"):
        raise ValueError(f"invalid space_kind: {space_kind!r}")

    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "perimeter",
                CellRecord.slug == slug,
            )
        )
        if row is None:
            return False

        if update_space_kind and space_kind is not None:
            row.space_kind = space_kind

        if update_triggers:
            if triggers_functional_cell_id is None:
                row.triggers_functional_cell_id = None
            else:
                tgt = session.scalar(
                    select(CellRecord).where(
                        CellRecord.id == triggers_functional_cell_id,
                        CellRecord.board_uuid == board_id,
                        CellRecord.kind == "functional",
                    )
                )
                if tgt is None:
                    raise ValueError(
                        "triggers_functional_cell_id must reference a panel cell on this board"
                    )
                if tgt.id == row.id:
                    raise ValueError("cannot link a space cell to itself")
                row.triggers_functional_cell_id = triggers_functional_cell_id

        return True


def list_panel_cells_for_board(board_id: str) -> list[CellRecord]:
    """All functional (panel) cells for a board, ordered for UI dropdowns."""
    with session_scope() as session:
        return list(
            session.scalars(
                select(CellRecord)
                .where(
                    CellRecord.board_uuid == board_id,
                    CellRecord.kind == "functional",
                )
                .order_by(CellRecord.position_index, CellRecord.slug)
            )
        )


def export_land_triggers_by_design_slug(board_id: str) -> dict[str, str]:
    """Return ``{space_design_slug: panel_slug}`` for space rows with a land-trigger FK.

    One entry per space **design** row (``cells.slug`` matches catalog design id).
    Used by project export ``interaction_graph`` (see ``docs/project-export-spec.md`` §10).
    """
    from sqlalchemy.orm import aliased

    Panel = aliased(CellRecord)
    with session_scope() as session:
        rows = session.execute(
            select(CellRecord.slug, Panel.slug)
            .join(Panel, CellRecord.triggers_functional_cell_id == Panel.id)
            .where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "perimeter",
                CellRecord.triggers_functional_cell_id.is_not(None),
                Panel.board_uuid == board_id,
                Panel.kind == "functional",
            )
        ).all()
        return {str(a): str(b) for a, b in rows}


# ────────────────────────── backfill live FK ──────────────────────────


def backfill_live_asset_version_ids() -> dict[str, int]:
    """Set ``cells.live_asset_version_id`` to the newest ``asset_versions`` row per cell where NULL.

    Idempotent. Use after restoring history rows or when ``live_promote`` did not run.
    """
    import domains.spaces.assets.models  # noqa: F401
    import domains.boards.models  # noqa: F401

    with session_scope() as session:
        null_before = int(
            session.scalar(
                select(func.count())
                .select_from(CellRecord)
                .where(CellRecord.live_asset_version_id.is_(None))
            )
            or 0
        )

    filled = 0
    with session_scope() as session:
        for cell in session.scalars(
            select(CellRecord).where(CellRecord.live_asset_version_id.is_(None))
        ).all():
            av_id = session.scalar(
                select(AssetVersionRecord.id)
                .where(AssetVersionRecord.cell_id == cell.id)
                .order_by(AssetVersionRecord.ts_ms.desc())
                .limit(1)
            )
            if av_id is not None:
                cell.live_asset_version_id = av_id
                filled += 1

    with session_scope() as session:
        still_null = int(
            session.scalar(
                select(func.count())
                .select_from(CellRecord)
                .where(CellRecord.live_asset_version_id.is_(None))
            )
            or 0
        )

    return {
        "null_before": null_before,
        "filled_from_asset_versions": filled,
        "still_null": still_null,
    }


# ────────────────────────── disk + DB cleanup ──────────────────────────


def prune_cell_files(board_id: str, category: str, slug: str) -> dict[str, int]:
    """Remove on-disk and DB state for one cell, top-down.

    Use cases:

      * future cell-delete / cell-rename routes: callers invoke this
        before the conflicting cell is recreated under a new slug.
      * one-off cleanup of orphaned slugs surfaced by the storage audit
        (cells whose row was deleted long ago but whose history files
        remain).

    Steps (idempotent: each step skips silently if there's nothing to do):

      1. ``space_animations`` rows for this cell — delete via
         ``delete_committed_animation`` so each row's on-disk clip is
         unlinked alongside the DB row.
      2. ``workspace/animations/<cell_id>/`` — rmtree the per-cell
         animations dir (proposals, history, any stragglers).
      3. ``asset_versions`` rows for (board, category, slug) — bulk
         DELETE (the FK from ``cells.live_asset_version_id`` is
         ``ON DELETE SET NULL``).
      4. ``workspace/live/<cat>/<slug>.png`` — drop the live PNG.
      5. ``workspace/history/<cat>/<slug>/`` — rmtree the history dir.

    Returns a dict reporting how much was removed for the audit log.
    The cells row itself is **not** deleted — that's the caller's
    responsibility (rename keeps the row, delete tombstones it).
    """
    kind = category_to_kind(category)
    if kind is None:
        raise ValueError(f"unknown category: {category!r}")

    store = bs.get_store()
    stats = {
        "animations_rows": 0,
        "animation_files": 0,
        "asset_version_rows": 0,
        "live_files": 0,
        "history_files": 0,
    }

    cell_id = find_id(board_id, category, slug)

    if cell_id is not None:
        from domains.spaces.animations import repository as anim_repo  # noqa: PLC0415

        with session_scope() as session:
            anim_ids = list(
                session.scalars(
                    select(SpaceAnimationRecord.id).where(
                        SpaceAnimationRecord.cell_id == cell_id
                    )
                )
            )
        for aid in anim_ids:
            anim_repo.delete_committed_animation(aid)
            stats["animations_rows"] += 1

        anim_dir = f"workspace/animations/{cell_id}"
        anim_existing = store.list(board_id, anim_dir)
        if anim_existing:
            stats["animation_files"] += len(anim_existing)
            store.delete(board_id, anim_dir)

    with session_scope() as session:
        result = session.execute(
            delete(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == board_id,
                AssetVersionRecord.category == category,
                AssetVersionRecord.asset_id == slug,
            )
        )
        stats["asset_version_rows"] = int(result.rowcount or 0)

    if category == "centerpiece":
        live_rel = "workspace/live/centerpiece/centerpiece.png"
    else:
        live_rel = f"workspace/live/{category}/{slug}.png"
    if store.exists(board_id, live_rel):
        store.delete(board_id, live_rel)
        stats["live_files"] += 1

    history_rel = f"workspace/history/{category}/{slug}"
    history_files = store.list(board_id, history_rel)
    if history_files:
        stats["history_files"] += len(history_files)
        store.delete(board_id, history_rel)

    return stats

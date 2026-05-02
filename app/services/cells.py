"""Cell-level use cases.

Phase 1c: covers the read-side helpers that ``server.py`` needed inline
(``_cell_status``, ``_seed_history_if_needed``, missing-id calculators).
The mutating actions (regenerate / cleanup / promote) still go through
``pipeline_adapters`` for now and will follow the same shape when we
move them in Phase 1d/1e.

Categories used throughout the codebase: ``"spaces"``, ``"panels"``,
``"centerpiece"``. The centerpiece is a single cell with the fixed
``asset_id == "centerpiece"``.
"""

from __future__ import annotations

from dataclasses import dataclass

from board_svg import CellStatus

from services import asset_index
from services import asset_live
from storage.fs import workspace as fs_ws


# ────────────────────────── status / readiness ──────────────────────────


def has_generated_asset(board_id: str, category: str, asset_id: str) -> bool:
    """Truthy when the cell has a *live* PNG (or a legacy approved PNG that
    will be auto-seeded into ``live/`` on the next render).

    Mirrors ``server._has_generated_asset`` exactly so the missing-id
    calculation stays consistent.
    """
    if asset_live.resolved_live_path(board_id, category, asset_id).exists():
        return True
    if fs_ws.approved_path_legacy(board_id, category, asset_id).exists():
        return True
    return False


def missing_space_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        d["id"]
        for d in catalog.get("board_spaces", {}).get("designs", [])
        if not has_generated_asset(board_id, "spaces", d["id"])
    ]


def missing_panel_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        p["id"]
        for p in catalog.get("feature_panels", {}).get("panels", [])
        if not has_generated_asset(board_id, "panels", p["id"])
    ]


# ────────────────────────── legacy seeding shim ──────────────────────────


def seed_history_if_needed(board_id: str, category: str, asset_id: str) -> None:
    """If a legacy ``approved/<asset_id>.png`` exists but no ``live/``,
    seed both via ``boardfactory.assets.seed_from_legacy_approved``.

    Swallows pipeline exceptions because legacy boards are best-effort -
    a corrupt sidecar shouldn't take down the cell render.
    """
    if asset_live.resolved_live_path(board_id, category, asset_id).exists():
        return
    if not fs_ws.approved_path_legacy(board_id, category, asset_id).exists():
        return
    # Imports kept lazy to avoid pulling the pipeline into modules that don't
    # actually need it (e.g. tests of read-only services).
    from boardfactory import config as bf_config
    from boardfactory import assets as bf_assets

    with bf_config.scope_board(board_id):
        try:
            bf_assets.seed_from_legacy_approved(category, asset_id)
        except Exception:
            pass


# ────────────────────────── one-cell status ──────────────────────────


def cell_status(board_id: str, category: str, asset_id: str) -> CellStatus:
    """Status for one cell - live PNG presence, history count, asset URL.

    The history count falls back to legacy ``cleaned/`` only when there's
    no ``history/`` directory yet, for boards that haven't been touched
    since the live/history refactor.
    """
    seed_history_if_needed(board_id, category, asset_id)
    live = asset_live.resolved_live_path(board_id, category, asset_id)
    is_live = live.exists()

    history_pngs = fs_ws.list_history_pngs(board_id, category, asset_id)
    fs_count = len(history_pngs)
    db_count = asset_index.count_for_cell(board_id, category, asset_id)
    history_count = db_count if db_count > 0 else fs_count
    if history_count == 0:
        history_count = len(
            fs_ws.list_legacy_cleaned(
                board_id, category,
                asset_id if category != "centerpiece" else None,
            )
        )

    live_url = None
    if is_live:
        rel = live.relative_to(fs_ws.workspace_dir(board_id))
        live_url = f"/b/{board_id}/asset/{rel.as_posix()}?t={int(live.stat().st_mtime)}"

    return CellStatus(
        asset_id=asset_id,
        category=category,
        candidates=history_count,
        approved=is_live,
        approved_url=live_url,
    )


# ────────────────────────── batched stats for the board view ──────────────────────────


@dataclass(frozen=True)
class BoardCellStats:
    """Aggregate counts the board template needs."""

    space_status: dict[str, CellStatus]
    panel_status: dict[str, CellStatus]
    centerpiece_status: CellStatus

    designs_total: int
    panels_total: int
    designs_done: int
    panels_done: int
    missing_space_ids: list[str]
    missing_panel_ids: list[str]


def collect_board_stats(board_id: str, catalog: dict) -> BoardCellStats:
    designs = catalog.get("board_spaces", {}).get("designs", [])
    panels = catalog.get("feature_panels", {}).get("panels", [])

    space_status = {d["id"]: cell_status(board_id, "spaces", d["id"]) for d in designs}
    panel_status = {p["id"]: cell_status(board_id, "panels", p["id"]) for p in panels}
    cp_status = cell_status(board_id, "centerpiece", "centerpiece")

    return BoardCellStats(
        space_status=space_status,
        panel_status=panel_status,
        centerpiece_status=cp_status,
        designs_total=len(designs),
        panels_total=len(panels),
        designs_done=sum(1 for s in space_status.values() if s.approved),
        panels_done=sum(1 for s in panel_status.values() if s.approved),
        missing_space_ids=missing_space_ids(board_id, catalog),
        missing_panel_ids=missing_panel_ids(board_id, catalog),
    )

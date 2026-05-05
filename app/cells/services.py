"""Cell-level use cases.

Read-side helpers used by the board view: per-cell status, missing-id
calculators, and the batched ``BoardCellStats`` aggregate.

Categories used throughout the codebase: ``"spaces"``, ``"panels"``,
``"centerpiece"``. The centerpiece is a single cell with the fixed
``asset_id == "centerpiece"``.
"""

from __future__ import annotations

from dataclasses import dataclass

from views.board_svg import CellStatus

from routes import deps
from assets import repository as asset_index
from assets import services as asset_urls
from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws


# ────────────────────────── status / readiness ──────────────────────────


def has_generated_asset(board_id: str, category: str, asset_id: str) -> bool:
    """Truthy when the cell has a live PNG."""
    return bs.get_store().exists(board_id, fs_ws.live_rel(category, asset_id))


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


# ────────────────────────── one-cell status ──────────────────────────


def cell_status(board_id: str, category: str, asset_id: str) -> CellStatus:
    """Status for one cell — live PNG presence, history count, asset URL."""
    store = bs.get_store()
    live_rel = fs_ws.live_rel(category, asset_id)
    is_live = store.exists(board_id, live_rel)

    history_pngs = fs_ws.list_history_pngs(board_id, category, asset_id)
    fs_count = len(history_pngs)
    db_count = asset_index.count_for_cell(board_id, category, asset_id)
    history_count = db_count if db_count > 0 else fs_count

    live_url = None
    if is_live:
        # Strip the leading "workspace/" so it matches the existing
        # /b/<id>/asset/<workspace-relative> route. ``?t=<mtime_ms>`` must use
        # full milliseconds — see ``services.asset_urls``.
        rel = live_rel.removeprefix("workspace/")
        bpath = deps.board_http_prefix(board_id)
        live_url = asset_urls.board_asset_url(
            http_prefix=bpath,
            asset_relpath=rel,
            mtime_ms=store.stat(board_id, live_rel).mtime_ms,
        )

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

"""Board export orchestrator — ordered stages mutating ``BoardExportState``."""

from __future__ import annotations

import copy
from typing import Any, Callable

from exporter.state import BoardExportOptions, BoardExportResult, BoardExportState
from exporter.stages.assets import stage_asset_wiring
from exporter.stages.bundle import stage_write_project_json
from exporter.stages.geometry import stage_geometry
from exporter.stages.interaction_graph import stage_interaction_graph
from exporter.stages.polish import stage_polish

EXPORT_SCHEMA_VERSION = "0.1.0-draft"

# Ordered pipeline — polish runs after assets, before writing ``project.json``.
EXPORT_STAGES: tuple[Callable[[BoardExportState], None], ...] = (
    stage_geometry,
    stage_interaction_graph,
    stage_asset_wiring,
    stage_polish,
    stage_write_project_json,
)


def _bootstrap_project(state: BoardExportState) -> None:
    cat = state.catalog
    opts = state.options
    title = opts.game_title if opts.game_title is not None else str(cat.get("project") or "Board")
    summary = opts.game_summary if opts.game_summary is not None else ""

    state.project = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "bundle_assets_root": "assets",
        "game": {
            "id": state.board_id,
            "title": title,
            "summary": summary,
            "rules_uri": None,
        },
        "board": {},
        "spaces": [],
        "interaction_graph": [],
    }


def run_board_export(
    board_id: str,
    catalog: dict[str, Any],
    *,
    options: BoardExportOptions | None = None,
) -> BoardExportResult:
    """Run all registered export stages and return a ``project`` dict snapshot.

    When ``options.bundle_root`` is set, the final stage writes ``project.json``
    (or ``options.project_json_basename``) after geometry, graph, assets, and polish.

    Stages append human-readable strings to ``state.errors`` on failure;
    the run still completes so callers can inspect partial ``project`` data.
    """
    state = BoardExportState(
        board_id=board_id,
        catalog=catalog,
        project={},
        options=options or BoardExportOptions(),
    )
    _bootstrap_project(state)
    for stage in EXPORT_STAGES:
        stage(state)
    ok = len(state.errors) == 0
    return BoardExportResult(
        ok=ok,
        project=copy.deepcopy(state.project),
        errors=tuple(state.errors),
    )

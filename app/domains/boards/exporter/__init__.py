"""Board bundle exporter — ``project.json`` projection (see ``docs/board-exporter.md``)."""

from domains.boards.exporter.orchestrate import EXPORT_SCHEMA_VERSION, EXPORT_STAGES, run_board_export
from domains.boards.exporter.state import BoardExportOptions, BoardExportResult, BoardExportState
from domains.boards.exporter.stages.assets import stage_asset_wiring
from domains.boards.exporter.stages.bundle import stage_write_project_json
from domains.boards.exporter.stages.geometry import stage_geometry
from domains.boards.exporter.stages.interaction_graph import stage_interaction_graph
from domains.boards.exporter.stages.polish import stage_polish

__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "EXPORT_STAGES",
    "BoardExportOptions",
    "BoardExportResult",
    "BoardExportState",
    "run_board_export",
    "stage_asset_wiring",
    "stage_geometry",
    "stage_interaction_graph",
    "stage_polish",
    "stage_write_project_json",
]

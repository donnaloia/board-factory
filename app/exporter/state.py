"""Export run state — see ``docs/project-export-spec.md`` §9.2."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.board_store import BoardStore


@dataclass(slots=True)
class BoardExportOptions:
    """Optional inputs for the in-progress ``project.json`` shell."""

    game_title: str | None = None
    game_summary: str | None = None
    board_node_id: str = "board_main"
    #: When set, ``stage_asset_wiring`` probes ``workspace/live/…`` and fills
    #: ``spaces[].assets.still`` (``null`` if no promoted PNG yet).
    store: BoardStore | None = None
    #: When set, ``stage_asset_wiring`` may copy live PNGs here (requires ``store``).
    #: ``stage_write_project_json`` always writes ``project_json_basename`` when this is set.
    bundle_root: Path | None = None
    #: Written by ``stage_write_project_json`` when ``bundle_root`` is set.
    project_json_basename: str = "project.json"
    #: When **not** ``None``, ``stage_interaction_graph`` uses this map (space design slug
    #: → panel slug) instead of querying ``cells``. Pass ``{}`` to force an empty graph
    #: without hitting the DB.
    land_triggers_design_to_panel: dict[str, str] | None = None
    #: Override default ``game_engine_instructions`` (LLM/engine handoff prose).
    game_engine_instructions: str | None = None
    #: When True (default), emit ``consumer_hints`` (Godot-oriented stub).
    include_consumer_hints: bool = True
    #: Replace default ``consumer_hints`` when set (non-``None``).
    consumer_hints: dict[str, Any] | None = None
    #: Skip ``_validate_export_project`` in ``stage_polish`` (tests only).
    skip_export_validation: bool = False


@dataclass(slots=True)
class BoardExportState:
    """Mutable state passed through each export stage."""

    board_id: str
    catalog: dict[str, Any]
    project: dict[str, Any]
    options: BoardExportOptions = field(default_factory=BoardExportOptions)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BoardExportResult:
    """Snapshot returned by ``run_board_export``."""

    ok: bool
    project: dict[str, Any]
    errors: tuple[str, ...]

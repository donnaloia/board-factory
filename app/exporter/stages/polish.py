"""Stage 5 — polish: handoff text, manifest, optional hints, lightweight validation (§9.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from exporter.state import BoardExportState

# Kept in sync with ``docs/project-export/example-starter-board.json`` (handoff prose).
_DEFAULT_GAME_ENGINE_INSTRUCTIONS = (
    "Paths are relative to the bundle root unless prefixed by bundle_assets_root. "
    "When generating Godot 4 code, import textures under res:// and map paths accordingly "
    "(or ResourceLoader.load after import). interaction_graph defines cross-space behavior; "
    "do not infer links only from space layout. spaces[].assets.animation may be null — "
    "skip AnimationPlayer setup when absent. Perimeter rects use the same math as "
    "app/domains/spaces/geometry.py:resolve_position and app/frontend/views/board_svg.py. "
    "docs/spec_prose.md explains the grid; real boards may differ from the default skeleton."
)

_DEFAULT_CONSUMER_HINTS: dict[str, Any] = {
    "primary_engine": "godot",
    "godot": {
        "major_version": 4,
        "suggested_scene_structure": (
            "BoardRoot (Node2D) -> SpaceSprites (Node2D per space id) -> "
            "InteractionController (Node)"
        ),
        "animation_delivery": (
            "Use AnimatedSprite2D or VideoStreamPlayer depending on format; "
            "APNG may need an addon or pre-split frames."
        ),
        "input_mapping_note": (
            "Map perimeter hit-testing from rect_canvas or separate collision polygons (export-TBD)."
        ),
    },
}


def _validate_export_project(project: dict[str, Any]) -> list[str]:
    """Return human-readable issues; empty means structure looks usable."""
    errs: list[str] = []

    if not isinstance(project.get("export_schema_version"), str):
        errs.append("polish: export_schema_version must be a non-empty string")
    if not isinstance(project.get("bundle_assets_root"), str):
        errs.append("polish: bundle_assets_root must be a string")

    game = project.get("game")
    if not isinstance(game, dict):
        errs.append("polish: game must be an object")
    else:
        if not isinstance(game.get("id"), str) or not game["id"]:
            errs.append("polish: game.id must be a non-empty string")
        if not isinstance(game.get("title"), str):
            errs.append("polish: game.title must be a string")

    board = project.get("board")
    if not isinstance(board, dict):
        errs.append("polish: board must be an object")
    else:
        cp = board.get("canvas_pixels")
        if not (isinstance(cp, list) and len(cp) == 2 and all(isinstance(x, int) for x in cp)):
            errs.append("polish: board.canvas_pixels must be [int, int]")

    spaces = project.get("spaces")
    if not isinstance(spaces, list):
        errs.append("polish: spaces must be an array")
    elif len(spaces) == 0:
        errs.append("polish: spaces must be non-empty when geometry succeeded")

    ig = project.get("interaction_graph")
    if not isinstance(ig, list):
        errs.append("polish: interaction_graph must be an array")

    if isinstance(spaces, list):
        for i, s in enumerate(spaces):
            if not isinstance(s, dict):
                errs.append(f"polish: spaces[{i}] must be an object")
                continue
            if not isinstance(s.get("id"), str) or not s["id"]:
                errs.append(f"polish: spaces[{i}].id missing")
            rc = s.get("rect_canvas")
            if not isinstance(rc, dict):
                errs.append(f"polish: spaces[{i}].rect_canvas must be an object")
            else:
                for k in ("x", "y", "width", "height"):
                    if k not in rc or not isinstance(rc[k], int):
                        errs.append(f"polish: spaces[{i}].rect_canvas.{k} must be int")
                        break

    if isinstance(ig, list):
        for i, e in enumerate(ig):
            if not isinstance(e, dict):
                errs.append(f"polish: interaction_graph[{i}] must be an object")
                continue
            for k in ("id", "from_space_id", "to_space_id", "link_kind", "trigger"):
                if k not in e:
                    errs.append(f"polish: interaction_graph[{i}] missing {k!r}")
                    break

    gei = project.get("game_engine_instructions")
    if gei is not None and not isinstance(gei, str):
        errs.append("polish: game_engine_instructions must be a string or absent")

    return errs


def stage_polish(state: BoardExportState) -> None:
    """Set handoff copy, ``export_manifest``, optional ``consumer_hints``, then validate."""
    opts = state.options
    proj = state.project

    if opts.game_engine_instructions is not None:
        proj["game_engine_instructions"] = opts.game_engine_instructions
    else:
        proj["game_engine_instructions"] = _DEFAULT_GAME_ENGINE_INSTRUCTIONS

    ver = proj.get("export_schema_version")
    if not isinstance(ver, str):
        ver = "0.1.0-draft"

    proj["export_manifest"] = {
        "exported_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_app": "board-factory",
        "export_schema_version": ver,
        "board_id": state.board_id,
    }

    if opts.include_consumer_hints:
        if opts.consumer_hints is not None:
            proj["consumer_hints"] = opts.consumer_hints
        else:
            proj["consumer_hints"] = _DEFAULT_CONSUMER_HINTS
    else:
        proj.pop("consumer_hints", None)

    if not opts.skip_export_validation:
        state.errors.extend(_validate_export_project(proj))

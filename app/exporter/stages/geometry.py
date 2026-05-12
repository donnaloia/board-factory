"""Stage 1 — canvas geometry for perimeter, panels, centerpiece (§5.2)."""

from __future__ import annotations

from typing import Any

from domains.cells.geometry import resolve_position

from exporter.state import BoardExportState


def _bbox_to_rect(bbox: list[int]) -> dict[str, int]:
    x1, y1, x2, y2 = bbox
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def _as_quad_ints(seq: Any) -> list[int] | None:
    if isinstance(seq, (list, tuple)) and len(seq) == 4:
        try:
            return [int(seq[0]), int(seq[1]), int(seq[2]), int(seq[3])]
        except (TypeError, ValueError):
            return None
    return None


def _perimeter_export_space_id(design_id: str, position_ref: str) -> str:
    safe = position_ref.replace(".", "_")
    return f"space__{design_id}__{safe}"


def stage_geometry(state: BoardExportState) -> None:
    """Fill ``board`` and ``spaces`` from ``state.catalog`` using ``resolve_position``.

    Asset paths are **placeholders** (same relative layout as the starter example);
    ``stage_asset_wiring`` overwrites ``still`` when a ``BoardStore`` is supplied.
    """
    catalog = state.catalog
    opts = state.options

    raw_bs = catalog.get("board_size")
    if isinstance(raw_bs, tuple) and len(raw_bs) == 2:
        board_size = [int(raw_bs[0]), int(raw_bs[1])]
    elif isinstance(raw_bs, list) and len(raw_bs) == 2:
        board_size = [int(raw_bs[0]), int(raw_bs[1])]
    else:
        state.errors.append("geometry: catalog.board_size must be [width, height]")
        return

    bs = catalog.get("board_spaces")
    if not isinstance(bs, dict):
        state.errors.append("geometry: catalog.board_spaces missing or not an object")
        return
    layout = bs.get("layout")
    designs = bs.get("designs")
    if not isinstance(layout, dict) or not isinstance(designs, list):
        state.errors.append("geometry: board_spaces.layout / board_spaces.designs invalid")
        return

    fp = catalog.get("feature_panels")
    if not isinstance(fp, dict) or not isinstance(fp.get("panels"), list):
        state.errors.append("geometry: catalog.feature_panels.panels missing")
        return
    panels: list[dict[str, Any]] = fp["panels"]

    cp = catalog.get("centerpiece")
    if not isinstance(cp, dict):
        state.errors.append("geometry: catalog.centerpiece missing or not an object")
        return
    bbox_cp = _as_quad_ints(cp.get("bbox"))
    if bbox_cp is None:
        state.errors.append("geometry: catalog.centerpiece.bbox must be four integers")
        return

    cw, ch = int(board_size[0]), int(board_size[1])

    layout_hint: dict[str, Any] = {
        "kind": "boardfactory_catalog_v1",
        "reference_implementation": "pipeline/boardfactory/boards.py:default_catalog_dict",
        "layout_math": "app/domains/cells/geometry.py:resolve_position",
        "prose_spec": "docs/spec_prose.md",
        "board_size": [cw, ch],
        "perimeter_layout_rows": layout,
    }

    state.project["board"] = {
        "id": opts.board_node_id,
        "canvas_pixels": [cw, ch],
        "coordinate_space": "canvas_pixels_top_left",
        "layout_hint": layout_hint,
    }

    spaces: list[dict[str, Any]] = []

    for design in designs:
        if not isinstance(design, dict):
            state.errors.append("geometry: invalid entry in board_spaces.designs")
            return
        did = design.get("id")
        positions = design.get("positions")
        if isinstance(positions, tuple):
            positions = list(positions)
        if not isinstance(did, str) or not isinstance(positions, list):
            state.errors.append(f"geometry: design missing id/positions: {design!r}")
            return
        for ref in positions:
            if not isinstance(ref, str):
                state.errors.append(f"geometry: non-string position ref under {did}")
                return
            try:
                x, y, w, h = resolve_position(layout, ref)
            except (KeyError, ValueError, TypeError) as e:
                state.errors.append(f"geometry: resolve_position({did!r}, {ref!r}): {e}")
                return
            sid = _perimeter_export_space_id(did, ref)
            spaces.append(
                {
                    "id": sid,
                    "role": "perimeter",
                    "display_name": f"{did} @ {ref}",
                    "catalog_ref": {
                        "kind": "board_space_design",
                        "design_id": did,
                        "position_ref": ref,
                    },
                    "rect_canvas": {"x": x, "y": y, "width": w, "height": h},
                    "assets": {
                        "still": f"assets/spaces/{did}/live.png",
                        "animation": None,
                    },
                    "z_index_hint": 0,
                }
            )

    for panel in panels:
        if not isinstance(panel, dict):
            state.errors.append("geometry: invalid entry in feature_panels.panels")
            return
        pid = panel.get("id")
        bbox = _as_quad_ints(panel.get("bbox"))
        if not isinstance(pid, str) or bbox is None:
            state.errors.append(f"geometry: panel missing id/bbox: {panel!r}")
            return
        rect = _bbox_to_rect(bbox)
        spaces.append(
            {
                "id": f"space_panel_{pid}",
                "role": "functional",
                "display_name": f"Functional panel {pid}",
                "catalog_ref": {"kind": "feature_panel", "panel_id": pid},
                "rect_canvas": rect,
                "assets": {
                    "still": f"assets/spaces/{pid}/live.png",
                    "animation": None,
                },
                "z_index_hint": 10,
            }
        )

    rect_cp = _bbox_to_rect(bbox_cp)
    spaces.append(
        {
            "id": "space_centerpiece",
            "role": "centerpiece",
            "display_name": "Centerpiece",
            "catalog_ref": {"kind": "centerpiece", "id": "centerpiece"},
            "rect_canvas": rect_cp,
            "assets": {
                "still": "assets/spaces/centerpiece/live.png",
                "animation": None,
            },
            "z_index_hint": 1,
        }
    )

    state.project["spaces"] = spaces

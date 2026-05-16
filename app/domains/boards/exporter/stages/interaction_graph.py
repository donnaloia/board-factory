"""Stage 4 — ``interaction_graph`` from land-trigger FKs (§9.2, §10)."""

from __future__ import annotations

import re
from typing import Any

from domains.spaces import repository as spaces_repo

from domains.boards.exporter.state import BoardExportState

_EDGE_ID_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _panel_export_space_id(panel_slug: str) -> str:
    return f"space_panel_{panel_slug}"


def _perimeter_space_ids_for_design(spaces: list[Any], design_slug: str) -> list[str]:
    """Every exported ``spaces[].id`` for perimeter tiles using ``design_slug``."""
    ids: list[str] = []
    for s in spaces:
        if not isinstance(s, dict):
            continue
        if s.get("role") != "perimeter":
            continue
        ref = s.get("catalog_ref")
        if not isinstance(ref, dict) or ref.get("design_id") != design_slug:
            continue
        sid = s.get("id")
        if isinstance(sid, str):
            ids.append(sid)
    return sorted(ids)


def _sanitize_edge_id(raw: str) -> str:
    s = _EDGE_ID_SAFE.sub("_", raw).strip("_")
    return s or "edge_land"


def _edge_payload(
    *,
    from_space_ids: list[str],
    to_space_id: str,
    design_slug: str,
    panel_slug: str,
) -> dict[str, Any]:
    """One land-trigger edge: perimeter design → functional panel animation.

    ``from_space_id`` is the first entry in ``from_space_ids`` (stable
    canonical). Engines should treat any id in ``from_space_ids``, or any
    perimeter tile whose ``catalog_ref.design_id`` equals
    ``trigger_space_design_id``, as a match for this edge.
    """
    eid = _sanitize_edge_id(f"edge_land__{design_slug}__{panel_slug}")
    canonical_from = from_space_ids[0]
    return {
        "id": eid,
        "from_space_id": canonical_from,
        "from_space_ids": list(from_space_ids),
        "trigger_space_design_id": design_slug,
        "to_space_id": to_space_id,
        "target_panel_id": panel_slug,
        "link_kind": "hidden_ui_route",
        "trigger": {
            "event": "land",
            "actions": [
                {
                    "type": "play_space_animation",
                    "target_space_id": to_space_id,
                    "target_panel_id": panel_slug,
                    "only_if_asset_present": True,
                }
            ],
        },
    }


def stage_interaction_graph(state: BoardExportState) -> None:
    """Fill ``project["interaction_graph"]`` from DB land triggers or an explicit map.

    Uses ``BoardExportOptions.land_triggers_design_to_panel``: when **``None``**
    (default), loads via ``spaces_repo.export_land_triggers_by_design_slug``.
    When set to a **dict** (possibly empty), uses that instead (tests / callers).

    Each edge lists **all** perimeter tile export ids for the linked design
    (``from_space_ids``), not only one canonical tile, so game engines can
    wire land-on-any-tile-of-this-design without inferring layout.
    """
    spaces = state.project.get("spaces")
    if not isinstance(spaces, list):
        return

    opts = state.options
    triggers = (
        opts.land_triggers_design_to_panel
        if opts.land_triggers_design_to_panel is not None
        else spaces_repo.export_land_triggers_by_design_slug(state.board_id)
    )

    space_ids = {s["id"] for s in spaces if isinstance(s, dict) and isinstance(s.get("id"), str)}

    edges: list[dict[str, Any]] = []
    for design_slug, panel_slug in sorted(triggers.items()):
        from_ids = _perimeter_space_ids_for_design(spaces, design_slug)
        if not from_ids:
            state.errors.append(
                f"interaction_graph: no exported perimeter space for design {design_slug!r}"
            )
            continue
        to_id = _panel_export_space_id(panel_slug)
        if to_id not in space_ids:
            state.errors.append(
                f"interaction_graph: target panel {panel_slug!r} not in export spaces "
                f"(expected id {to_id!r})"
            )
            continue
        edges.append(
            _edge_payload(
                from_space_ids=from_ids,
                to_space_id=to_id,
                design_slug=design_slug,
                panel_slug=panel_slug,
            )
        )

    state.project["interaction_graph"] = edges

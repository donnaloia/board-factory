"""Tests for ``app/exporter`` — geometry stage + orchestrator (no DB)."""

from __future__ import annotations

from boardfactory.boards import default_catalog_dict

from exporter.orchestrate import EXPORT_STAGES, run_board_export
from exporter.state import BoardExportOptions


def test_export_default_catalog_top_battle_rect():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "Probe")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    battle = next(
        s
        for s in res.project["spaces"]
        if s.get("catalog_ref", {}).get("design_id") == "top_battle"
        and s.get("catalog_ref", {}).get("position_ref") == "top_row.3"
    )
    assert battle["rect_canvas"] == {"x": 480, "y": 0, "width": 160, "height": 180}
    assert battle["id"] == "space__top_battle__top_row_3"


def test_export_panel_right_mid_matches_board_svg_bbox():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "Probe")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    p = next(s for s in res.project["spaces"] if s["id"] == "space_panel_panel_right_mid")
    assert p["rect_canvas"] == {"x": 1480, "y": 420, "width": 260, "height": 240}
    assert p["role"] == "functional"


def test_export_centerpiece_rect():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "Probe")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    cp = next(s for s in res.project["spaces"] if s["id"] == "space_centerpiece")
    assert cp["rect_canvas"] == {"x": 700, "y": 180, "width": 520, "height": 720}


def test_export_perimeter_slot_count_matches_catalog_positions():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "Probe")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    n_perim = sum(len(d["positions"]) for d in cat["board_spaces"]["designs"])
    n_func = len(cat["feature_panels"]["panels"])
    n_spaces = len(res.project["spaces"])
    assert n_spaces == n_perim + n_func + 1


def test_board_export_options_title_and_board_id():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "CatTitle")
    res = run_board_export(
        "00000000-0000-4000-8000-000000000099",
        cat,
        options=BoardExportOptions(game_title="Override", board_node_id="custom_board"),
    )
    assert res.ok, res.errors
    assert res.project["game"]["title"] == "Override"
    assert res.project["game"]["id"] == "00000000-0000-4000-8000-000000000099"
    assert res.project["board"]["id"] == "custom_board"


def test_geometry_surfaces_errors_on_bad_catalog():
    res = run_board_export("x", {})
    assert not res.ok
    assert res.errors
    assert "geometry:" in res.errors[0]

    res2 = run_board_export("x", {"board_size": [640, 480]})
    assert not res2.ok
    assert any("board_spaces" in e for e in res2.errors)


def test_export_stages_order():
    assert [s.__name__ for s in EXPORT_STAGES] == [
        "stage_geometry",
        "stage_interaction_graph",
        "stage_asset_wiring",
        "stage_polish",
        "stage_write_project_json",
    ]

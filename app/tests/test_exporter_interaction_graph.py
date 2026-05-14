"""Tests for ``stage_interaction_graph`` + ``export_land_triggers_by_design_slug``."""

from __future__ import annotations

from boardfactory.boards import default_catalog_dict

from domains.spaces import repository as spaces_repo

from exporter.orchestrate import run_board_export
from exporter.state import BoardExportOptions


def test_export_land_triggers_by_design_slug_db(isolated_repo, seeded_board, board_id):
    pid = spaces_repo.find_id(board_id, "panels", "panel_left_top")
    assert pid
    spaces_repo.patch_space_cell_metadata(
        board_id,
        "top_battle",
        update_triggers=True,
        triggers_functional_cell_id=pid,
    )
    m = spaces_repo.export_land_triggers_by_design_slug(board_id)
    assert m == {"top_battle": "panel_left_top"}


def test_interaction_graph_explicit_map():
    bid = "00000000-0000-4000-8000-0000000000dd"
    cat = default_catalog_dict(bid, "G")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={"top_battle": "panel_right_mid"},
        ),
    )
    assert res.ok, res.errors
    g = res.project["interaction_graph"]
    assert len(g) == 1
    e = g[0]
    assert e["from_space_id"] == "space__top_battle__top_row_3"
    assert e["to_space_id"] == "space_panel_panel_right_mid"
    assert e["link_kind"] == "hidden_ui_route"
    assert e["trigger"]["event"] == "land"
    assert e["trigger"]["actions"][0]["type"] == "play_space_animation"
    assert e["trigger"]["actions"][0]["target_space_id"] == "space_panel_panel_right_mid"


def test_interaction_graph_empty_override_skips_db():
    bid = "00000000-0000-4000-8000-0000000000ee"
    cat = default_catalog_dict(bid, "G")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(land_triggers_design_to_panel={}),
    )
    assert res.ok, res.errors
    assert res.project["interaction_graph"] == []


def test_interaction_graph_errors_on_unknown_panel_slug():
    bid = "00000000-0000-4000-8000-0000000000ff"
    cat = default_catalog_dict(bid, "G")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={"top_battle": "not_a_real_panel_slug"},
        ),
    )
    assert not res.ok
    assert any("interaction_graph" in err for err in res.errors)


def test_interaction_graph_errors_on_unknown_design():
    bid = "00000000-0000-4000-8000-0000000000ab"
    cat = default_catalog_dict(bid, "G")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={"not_a_design": "panel_right_mid"},
        ),
    )
    assert not res.ok


def test_interaction_graph_from_db_after_patch(isolated_repo, seeded_board, board_id):
    from boardfactory import boards as bf_boards

    pid = spaces_repo.find_id(board_id, "panels", "panel_left_top")
    assert pid
    spaces_repo.patch_space_cell_metadata(
        board_id,
        "corner_tl",
        update_triggers=True,
        triggers_functional_cell_id=pid,
    )
    cat = bf_boards.default_catalog_dict(board_id, seeded_board.project)
    res = run_board_export(board_id, cat)
    assert res.ok, res.errors
    edges = res.project["interaction_graph"]
    assert len(edges) == 1
    assert edges[0]["from_space_id"] == "space__corner_tl__top_row_0"
    assert edges[0]["to_space_id"] == "space_panel_panel_left_top"

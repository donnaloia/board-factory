"""Tests for ``stage_polish`` (§9.2 stage 5)."""

from __future__ import annotations

import json

from boardfactory.boards import default_catalog_dict

from exporter import run_board_export
from exporter.state import BoardExportOptions


def test_polish_adds_handoff_manifest_and_hints():
    bid = "00000000-0000-4000-8000-0000000000c1"
    cat = default_catalog_dict(bid, "P")
    res = run_board_export(bid, cat, options=BoardExportOptions(land_triggers_design_to_panel={}))
    assert res.ok, res.errors
    p = res.project
    assert "game_engine_instructions" in p
    assert "interaction_graph" in p["game_engine_instructions"]
    assert "export_manifest" in p
    assert p["export_manifest"]["generator_app"] == "board-factory"
    assert p["export_manifest"]["export_schema_version"] == p["export_schema_version"]
    assert p["export_manifest"]["board_id"] == bid
    assert p["export_manifest"]["exported_at"].endswith("Z")
    assert p["consumer_hints"]["primary_engine"] == "godot"
    assert p["consumer_hints"]["godot"]["major_version"] == 4


def test_polish_custom_game_engine_instructions():
    bid = "00000000-0000-4000-8000-0000000000c2"
    cat = default_catalog_dict(bid, "P")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={},
            game_engine_instructions="Custom handoff only.",
        ),
    )
    assert res.ok, res.errors
    assert res.project["game_engine_instructions"] == "Custom handoff only."


def test_polish_omit_consumer_hints():
    bid = "00000000-0000-4000-8000-0000000000c3"
    cat = default_catalog_dict(bid, "P")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={},
            include_consumer_hints=False,
        ),
    )
    assert res.ok, res.errors
    assert "consumer_hints" not in res.project


def test_polish_custom_consumer_hints():
    bid = "00000000-0000-4000-8000-0000000000c4"
    cat = default_catalog_dict(bid, "P")
    custom = {"primary_engine": "unity", "unity": {"note": "stub"}}
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            land_triggers_design_to_panel={},
            consumer_hints=custom,
        ),
    )
    assert res.ok, res.errors
    assert res.project["consumer_hints"] == custom


def test_polish_written_json_includes_polish(tmp_path):
    bid = "00000000-0000-4000-8000-0000000000c5"
    cat = default_catalog_dict(bid, "P")
    root = tmp_path / "out"
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(land_triggers_design_to_panel={}, bundle_root=root),
    )
    assert res.ok, res.errors
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert "export_manifest" in data
    assert "game_engine_instructions" in data

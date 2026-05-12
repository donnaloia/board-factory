"""Tests for ``stage_write_project_json`` (bundle packaging, §9.2)."""

from __future__ import annotations

import json

from boardfactory.boards import default_catalog_dict

from exporter import run_board_export
from exporter.state import BoardExportOptions


def test_bundle_writes_project_json_without_store(tmp_path):
    bid = "00000000-0000-4000-8000-0000000000aa"
    cat = default_catalog_dict(bid, "Titles 日本語")
    root = tmp_path / "bundle_only"
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(bundle_root=root),
    )
    assert res.ok, res.errors
    path = root / "project.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == res.project
    assert res.project["game"]["title"] == "Titles 日本語"


def test_bundle_custom_project_json_basename(tmp_path):
    bid = "00000000-0000-4000-8000-0000000000bb"
    cat = default_catalog_dict(bid, "X")
    root = tmp_path / "out"
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(bundle_root=root, project_json_basename="manifest.json"),
    )
    assert res.ok, res.errors
    assert (root / "manifest.json").is_file()
    assert not (root / "project.json").exists()


def test_bundle_rejects_bad_project_json_basename(tmp_path):
    bid = "00000000-0000-4000-8000-0000000000cc"
    cat = default_catalog_dict(bid, "X")
    res = run_board_export(
        bid,
        cat,
        options=BoardExportOptions(
            bundle_root=tmp_path / "z",
            project_json_basename="escape/attempt.json",
        ),
    )
    assert not res.ok
    assert any("project_json_basename" in e for e in res.errors)

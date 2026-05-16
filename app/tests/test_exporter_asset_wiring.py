"""Tests for ``stage_asset_wiring`` — ``BoardStore`` + optional bundle copy."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from boardfactory.boards import default_catalog_dict

from domains.boards.exporter.orchestrate import EXPORT_STAGES, run_board_export
from domains.boards.exporter.state import BoardExportOptions


_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_asset_wiring_skipped_without_store():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "X")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    assert EXPORT_STAGES[1].__name__ == "stage_interaction_graph"
    assert EXPORT_STAGES[2].__name__ == "stage_asset_wiring"
    assert EXPORT_STAGES[3].__name__ == "stage_animation_wiring"
    assert EXPORT_STAGES[4].__name__ == "stage_polish"
    assert EXPORT_STAGES[5].__name__ == "stage_write_project_json"
    first = next(s for s in res.project["spaces"] if s["id"] == "space__corner_tl__top_row_0")
    assert first["assets"]["still"] == "assets/spaces/corner_tl/live.png"


def test_asset_wiring_nulls_still_when_live_missing():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "X")

    class _EmptyStore:
        def exists(self, board_id: str, rel: str) -> bool:
            return False

        def read_bytes(self, board_id: str, rel: str) -> bytes:
            raise AssertionError("read_bytes should not run when exists is False")

    res = run_board_export(
        "00000000-0000-4000-8000-000000000001",
        cat,
        options=BoardExportOptions(store=_EmptyStore()),  # type: ignore[arg-type]
    )
    assert res.ok, res.errors
    first = res.project["spaces"][0]
    assert first["assets"]["still"] is None


def test_asset_wiring_sets_path_without_copy_when_live_present():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "X")
    rel = "workspace/live/spaces/top_battle.png"

    class _MemStore:
        def exists(self, board_id: str, r: str) -> bool:
            return r == rel

        def read_bytes(self, board_id: str, r: str) -> bytes:
            assert r == rel
            return _MIN_PNG

    res = run_board_export(
        "00000000-0000-4000-8000-000000000001",
        cat,
        options=BoardExportOptions(store=_MemStore(), bundle_root=None),  # type: ignore[arg-type]
    )
    assert res.ok, res.errors
    battles = [
        s
        for s in res.project["spaces"]
        if s.get("catalog_ref", {}).get("design_id") == "top_battle"
    ]
    assert battles
    assert all(s["assets"]["still"] == "assets/spaces/top_battle/live.png" for s in battles)


def test_asset_wiring_copies_into_bundle_root(isolated_repo, seeded_board, board_id, tmp_path):
    from boardfactory import boards as bf_boards
    from infrastructure import board_store as bs
    from infrastructure.files import workspace as fs_ws

    rel = fs_ws.live_rel("spaces", "top_battle")
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), (200, 10, 99, 255)).save(buf, format="PNG")
    bs.get_store().write_bytes(board_id, rel, buf.getvalue())

    cat = bf_boards.default_catalog_dict(board_id, seeded_board.project)
    out_root = tmp_path / "export_bundle"
    res = run_board_export(
        board_id,
        cat,
        options=BoardExportOptions(store=bs.get_store(), bundle_root=out_root),
    )
    assert res.ok, res.errors

    copied = out_root / "assets" / "spaces" / "top_battle" / "live.png"
    assert copied.is_file()
    assert copied.read_bytes() == buf.getvalue()

    battles = [
        s
        for s in res.project["spaces"]
        if s.get("catalog_ref", {}).get("design_id") == "top_battle"
    ]
    assert len(battles) == 1
    assert battles[0]["assets"]["still"] == "assets/spaces/top_battle/live.png"

    pj = out_root / "project.json"
    assert pj.is_file()
    assert json.loads(pj.read_text(encoding="utf-8"))["game"]["id"] == board_id


@pytest.mark.parametrize("category, asset_id, subdir", [
    ("panels", "panel_right_mid", "panel_right_mid"),
    ("centerpiece", "centerpiece", "centerpiece"),
])
def test_asset_wiring_panel_and_centerpiece_copy(
    isolated_repo, seeded_board, board_id, tmp_path, category, asset_id, subdir
):
    from boardfactory import boards as bf_boards
    from infrastructure import board_store as bs
    from infrastructure.files import workspace as fs_ws

    rel = fs_ws.live_rel(category, asset_id)
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(buf, format="PNG")
    bs.get_store().write_bytes(board_id, rel, buf.getvalue())

    cat = bf_boards.default_catalog_dict(board_id, seeded_board.project)
    out_root = tmp_path / "b"
    res = run_board_export(
        board_id,
        cat,
        options=BoardExportOptions(store=bs.get_store(), bundle_root=out_root),
    )
    assert res.ok, res.errors
    dest = out_root / "assets" / "spaces" / subdir / "live.png"
    assert dest.is_file()
    assert (out_root / "project.json").is_file()

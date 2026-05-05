"""Service-layer tests for cell status / readiness."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def _write_png(path: Path, color=(60, 80, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (*color, 255)).save(path)


def test_cell_status_no_live_no_history(seeded_board, isolated_repo):
    from cells import services as svc_cells

    status = svc_cells.cell_status(seeded_board.id, "spaces", "corner_tl")
    assert status.approved is False
    assert status.approved_url is None
    assert status.candidates == 0


def test_cell_status_with_live_png(seeded_board, path_slug, test_user, isolated_repo):
    from cells import services as svc_cells
    from infrastructure.files import workspace as fs_ws

    _write_png(fs_ws.live_path(seeded_board.id, "spaces", "corner_tl"))

    status = svc_cells.cell_status(seeded_board.id, "spaces", "corner_tl")
    assert status.approved is True
    assert status.approved_url is not None
    assert f"/users/{test_user.username}/board-games/{path_slug}/asset/live/spaces/corner_tl.png" in status.approved_url


def test_missing_ids_excludes_cells_with_live(seeded_board, isolated_repo):
    from cells import services as svc_cells
    from boards import services as svc_catalog
    from infrastructure.files import workspace as fs_ws

    catalog = svc_catalog.load_catalog(seeded_board.id)
    full_missing = svc_cells.missing_space_ids(seeded_board.id, catalog)
    assert "corner_tl" in full_missing

    _write_png(fs_ws.live_path(seeded_board.id, "spaces", "corner_tl"))

    after = svc_cells.missing_space_ids(seeded_board.id, catalog)
    assert "corner_tl" not in after


def test_collect_board_stats(seeded_board, isolated_repo):
    from cells import services as svc_cells
    from boards import services as svc_catalog
    from infrastructure.files import workspace as fs_ws

    catalog = svc_catalog.load_catalog(seeded_board.id)

    # Promote one space + one panel + the centerpiece.
    _write_png(fs_ws.live_path(seeded_board.id, "spaces", "corner_tl"))
    _write_png(fs_ws.live_path(seeded_board.id, "panels", "panel_left_top"))
    _write_png(fs_ws.live_path(seeded_board.id, "centerpiece", "centerpiece"))

    stats = svc_cells.collect_board_stats(seeded_board.id, catalog)

    assert stats.designs_total == len(catalog["board_spaces"]["designs"])
    assert stats.panels_total == len(catalog["feature_panels"]["panels"])
    assert stats.designs_done == 1
    assert stats.panels_done == 1
    assert stats.centerpiece_status.approved is True
    assert "corner_tl" not in stats.missing_space_ids
    assert "panel_left_top" not in stats.missing_panel_ids

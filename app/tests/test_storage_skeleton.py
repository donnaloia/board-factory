"""Smoke tests for storage wiring and the pytest harness.

Verifies SQLAlchemy session usage, isolated-repo pipeline config, and basic
service integration; extend this file when adding storage-focused regressions.
"""

from __future__ import annotations


import pytest


def test_engine_uses_overridden_url(db_engine):
    assert db_engine is not None
    assert "sqlite" in str(db_engine.url)


def test_session_scope_commits_and_rolls_back(db_engine):
    from sqlalchemy import text

    from storage.db import session_scope

    with session_scope() as session:
        result = session.execute(text("SELECT 1")).scalar_one()
    assert result == 1


def test_pipeline_module_loads_under_isolated_repo(isolated_repo):
    """Importing the pipeline package should pick up our temp REPO_ROOT."""
    import importlib

    import boardfactory.config as cfg  # type: ignore

    importlib.reload(cfg)
    assert str(cfg.REPO_ROOT) == str(isolated_repo)


def test_seeded_board_creates_catalog(seeded_board, isolated_repo):
    from services import board_definition as bd

    assert bd.load_catalog_dict(seeded_board.id) is not None
    assert (isolated_repo / "boards" / seeded_board.id / "mockup" / "board.png").exists()


def test_config_has_no_legacy_cli_path_attrs(isolated_repo):
    """Legacy staging dirs are not exposed on ``boardfactory.config``."""
    import importlib

    import boardfactory.config as cfg  # type: ignore

    importlib.reload(cfg)
    with pytest.raises(AttributeError):
        _ = cfg.APPROVED_DIR  # type: ignore[attr-defined]


def test_migrate_legacy_board_assets_to_export(isolated_repo, seeded_board, board_id):
    import shutil

    from storage.fs import workspace as fs_ws

    root = fs_ws.board_root(board_id)
    exp = fs_ws.export_dir(board_id)
    if exp.exists():
        shutil.rmtree(exp)
    legacy = root / "board_assets"
    legacy.mkdir(parents=True)
    (legacy / "marker.txt").write_text("x")
    assert not fs_ws.export_dir(board_id).exists()
    fs_ws.migrate_legacy_board_assets_to_export(board_id)
    assert fs_ws.export_dir(board_id).exists()
    assert (fs_ws.export_dir(board_id) / "marker.txt").read_text() == "x"
    assert not legacy.exists()


def test_legacy_cli_workspace_trees_exist(isolated_repo, seeded_board, board_id):
    from storage.fs import workspace as fs_ws

    assert fs_ws.legacy_cli_workspace_trees_exist(board_id) is False
    (fs_ws.workspace_dir(board_id) / "approved").mkdir(parents=True)
    assert fs_ws.legacy_cli_workspace_trees_exist(board_id) is True

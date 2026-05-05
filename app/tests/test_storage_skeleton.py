"""Smoke tests for storage wiring and the pytest harness.

Verifies SQLAlchemy session usage, isolated-repo pipeline config, and basic
service integration; extend this file when adding storage-focused regressions.
"""

from __future__ import annotations


import pytest


def test_engine_uses_overridden_url(db_engine):
    assert db_engine is not None
    assert db_engine.url.get_backend_name() == "postgresql"


def test_session_scope_commits_and_rolls_back(db_engine):
    from sqlalchemy import text

    from infrastructure.db import session_scope

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
    from boards import services as bd
    from infrastructure import board_store as bs

    assert bd.load_catalog_dict(seeded_board.id) is not None
    assert bs.get_store().exists(seeded_board.id, "mockup/board.png")


def test_config_has_no_legacy_cli_path_attrs(isolated_repo):
    """Legacy staging dirs are not exposed on ``boardfactory.config``."""
    import importlib

    import boardfactory.config as cfg  # type: ignore

    importlib.reload(cfg)
    with pytest.raises(AttributeError):
        _ = cfg.APPROVED_DIR  # type: ignore[attr-defined]

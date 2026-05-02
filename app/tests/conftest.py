"""Shared pytest fixtures for the Board Factory web application.

Goals:

* Run pipeline + app code against an isolated, on-disk repo root that
  goes away at end-of-test - no leakage into ``boards/`` on the dev tree.
* Give every test a SQLite engine pointing at the same temp tree, with the
  database schema brought up to head before the test starts (full Alembic chain).
* Default the image provider to the offline ``mock`` so tests never reach
  out to OpenAI / PixelLab and never need an API key.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

# Make the ``app/`` package importable when pytest is invoked from the
# repo root. Inside the container these are already on sys.path under /app,
# but on a developer laptop they aren't.
_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

# Boardfactory pipeline package lives next to ``app/`` at repo ``pipeline/``.
_PIPELINE = _APP_ROOT.parent / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))


@pytest.fixture(autouse=True)
def isolated_repo(tmp_path, monkeypatch):
    """Point every BOARDFACTORY_* path at a throwaway tmp tree.

    The pipeline reads ``BOARDFACTORY_REPO`` to find ``boards/<id>/``.
    Tests must never write into the developer's real boards directory.
    """
    repo = tmp_path / "repo"
    (repo / "boards").mkdir(parents=True)
    (repo / "workspace").mkdir(parents=True)

    monkeypatch.setenv("BOARDFACTORY_REPO", str(repo))
    monkeypatch.setenv("BOARDFACTORY_PROVIDER", "mock")
    monkeypatch.setenv("BOARDFACTORY_DB_PATH", str(repo / ".boardfactory.db"))
    # Don't carry real keys into tests.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PIXELLAB_API_KEY", raising=False)

    from alembic import command
    from alembic.config import Config

    import storage.db as storage_db

    storage_db.dispose_engine()
    storage_db.override_database_url(None)
    ini_path = _APP_ROOT / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(_APP_ROOT / "migrations"))
    command.upgrade(cfg, "head")

    # Migrations seed a dev admin; tests expect an empty ``users`` table so
    # ``create_first_user`` / registration flows still apply.
    import sqlalchemy as sa

    import storage.db as storage_db

    storage_db.dispose_engine()
    storage_db.override_database_url(None)
    eng = storage_db.get_engine()
    with eng.begin() as conn:
        for stmt in (
            "DELETE FROM browser_sessions",
            "DELETE FROM user_secrets",
            "DELETE FROM owned_boards",
            "DELETE FROM users",
        ):
            conn.execute(sa.text(stmt))

    # Some modules cache REPO_ROOT at import time. Reload them so the
    # fixture's monkeypatched env wins for the duration of the test.
    import importlib

    for mod_name in (
        "boardfactory.config",
        "boardfactory",
        "users",
        "cost_ledger",
        "sessions",
        "storage.db",
    ):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            importlib.reload(mod)

    yield repo

    # tmp_path is auto-cleaned by pytest; this is just defensive.
    shutil.rmtree(repo, ignore_errors=True)


@pytest.fixture
def db_engine(isolated_repo):
    """A clean SQLAlchemy engine pointing at the temp tree.

    Ensures ``session_scope`` talks to the temp SQLite file created by migrations.
    """
    from storage import db as storage_db

    storage_db.dispose_engine()
    storage_db.override_database_url(f"sqlite:///{isolated_repo / '.boardfactory.db'}")
    engine = storage_db.get_engine()
    yield engine
    storage_db.dispose_engine()
    storage_db.override_database_url(None)


@pytest.fixture
def board_id() -> str:
    return "test-board"


@pytest.fixture
def test_user(isolated_repo):
    """Single test account (fresh DB allows first-user registration)."""
    import users as users_mod

    return users_mod.create_first_user(
        email="tester@example.com",
        password="password123",
        display_name="Tester",
    )


@pytest.fixture
def seeded_board(isolated_repo, board_id, test_user):
    """Create a minimal but valid board on disk and return its info.

    Uses the pipeline's own ``boards.create_board`` helper so we exercise
    the real catalog skeleton; the only post-hoc edits are filling prompts
    so generation has something to send to the mock provider.
    """
    from boardfactory import boards as bf_boards

    from services import board_ownership as bo

    info = bf_boards.create_board(board_id, project_name="Test Board")
    from services import board_definition as bd

    bd.persist_catalog_dict(board_id, bf_boards.default_catalog_dict(board_id, "Test Board"))
    bo.link_board_to_user(board_id, test_user.id)

    # Drop a tiny PNG into mockup/ so anything that needs the reference
    # image can find one.
    from PIL import Image

    mockup_dir = isolated_repo / "boards" / board_id / "mockup"
    mockup_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1920, 1080), (32, 32, 40)).save(mockup_dir / "board.png")

    return info

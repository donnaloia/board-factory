"""Shared pytest fixtures for the Board Factory web application.

Goals:

* Run pipeline + app code against an isolated, on-disk repo root that
  goes away at end-of-test - no leakage into ``data/boards/`` on the dev tree.
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

    The pipeline reads ``BOARDFACTORY_REPO`` to find the per-board data
    root (``data/boards/<id>/`` by default). Tests must never write into
    the developer's real data directory.
    """
    repo = tmp_path / "repo"
    (repo / "data" / "boards").mkdir(parents=True)
    (repo / "workspace").mkdir(parents=True)

    monkeypatch.setenv("BOARDFACTORY_REPO", str(repo))
    monkeypatch.setenv("BOARDFACTORY_PROVIDER", "mock")
    monkeypatch.setenv("BOARDFACTORY_DB_PATH", str(repo / ".boardfactory.db"))
    # Pin the data root explicitly so any earlier test's cached store
    # singleton (or any module that captured BOARDFACTORY_REPO at import)
    # cannot leak in.
    monkeypatch.setenv("BOARDFACTORY_BOARDS_DIR", str(repo / "data" / "boards"))
    # Don't carry real keys into tests.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PIXELLAB_API_KEY", raising=False)

    # Drop any cached BoardStore from a previous test before any code
    # under test (or Alembic's env.py) has a chance to call ``get_store()``
    # against the stale singleton.
    from storage import board_store as _bs

    _bs.reset_store()

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
            "DELETE FROM asset_versions",
            "DELETE FROM owned_boards",
            "DELETE FROM board_games",
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

    from boardfactory import config as _bf_config
    from services import board_paths as _board_paths

    _bf_config.set_board_root_resolver(_board_paths.store_board_root)

    # ``storage.board_store`` is _not_ reloaded — reloading would create
    # a fresh ``_store`` module-level slot but other modules already hold
    # a reference to the old module's ``get_store`` / ``reset_store``
    # functions. We instead drop the singleton in-place via reset_store()
    # at the start of the fixture.

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
def path_slug() -> str:
    return "test-board"


@pytest.fixture
def board_id(seeded_board):
    return seeded_board.id


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
def seeded_board(isolated_repo, path_slug, test_user):
    """Create a minimal but valid board on disk and return ``BoardInfo``."""
    import io as _io
    import uuid as _uuid

    from PIL import Image

    from boardfactory import boards as bf_boards

    from services import board_definition as bd
    from services import board_ownership as bo
    from storage import board_store as bs

    bu = str(_uuid.uuid4())
    bd.persist_catalog_dict(bu, bf_boards.default_catalog_dict(bu, "Test Board"))
    bo.link_board_to_user(bu, test_user.id, path_slug=path_slug)
    bs.get_store().create_board_skeleton(bu)

    buf = _io.BytesIO()
    Image.new("RGB", (1920, 1080), (32, 32, 40)).save(buf, format="PNG")
    bs.get_store().write_bytes(bu, "mockup/board.png", buf.getvalue())

    info = bf_boards.get_board(bu)
    assert info is not None
    return info

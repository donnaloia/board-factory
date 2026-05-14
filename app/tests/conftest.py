"""Shared pytest fixtures for the Board Factory web application.

Goals:

* Run pipeline + app code against an isolated, on-disk repo root that
  goes away at end-of-test - no leakage into ``data/boards/`` on the dev tree.
* Give every test a Postgres engine pointing at a session-scoped
  ``boardfactory_test`` database, with the schema brought up to head once
  per pytest session and tables ``TRUNCATE``d between tests for isolation.
* Default the image provider to the offline ``mock`` so tests never reach
  out to OpenAI / PixelLab and never need an API key.

Postgres is the only supported backend. The test DB name is taken from
``BOARDFACTORY_TEST_DATABASE`` (default ``boardfactory_test``) and is
created on first use against the same server / credentials as the runtime
``BOARDFACTORY_DATABASE_URL``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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


def _runtime_database_url() -> str:
    """Postgres URL the running app uses. Tests build a sibling test DB from this."""
    url = os.environ.get("BOARDFACTORY_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "BOARDFACTORY_DATABASE_URL must be set when running the test suite. "
            "Run app tests inside Docker (not on the host): `make up` then `make test` "
            "from the repo root, or `docker compose exec -T board-factory sh -c 'cd /app && "
            "PYTHONPATH=/app:/repo/pipeline python -m pytest …'` — see Makefile `test` target. "
            "Inside the board-factory container this URL is set by docker-compose.yml."
        )
    return url


def _swap_database_name(url: str, db_name: str) -> str:
    """Return ``url`` with the path component replaced by ``/<db_name>``."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{db_name}"))


def _ensure_test_database(test_db: str) -> None:
    """Create the test DB if it doesn't exist (idempotent)."""
    import sqlalchemy as sa

    admin_url = _swap_database_name(_runtime_database_url(), "postgres")
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": test_db},
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{test_db}"'))
    finally:
        engine.dispose()


def _truncate_all_tables() -> None:
    """Wipe data from every Alembic-managed table (keeps schema, drops rows)."""
    import sqlalchemy as sa

    import infrastructure.db as storage_db

    eng = storage_db.get_engine()
    with eng.begin() as conn:
        # alembic_version isn't in the app data set; leave it so the schema
        # stays at HEAD across tests.
        rows = conn.execute(
            sa.text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename <> 'alembic_version'
                """
            )
        ).fetchall()
        names = [r[0] for r in rows]
        if not names:
            return
        # RESTART IDENTITY resets autoincrement counters; CASCADE handles FKs.
        quoted = ", ".join(f'"{n}"' for n in names)
        conn.execute(sa.text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def _test_database_url() -> str:
    """Resolve the test DB URL once per pytest session and run migrations against it."""
    test_db = os.environ.get("BOARDFACTORY_TEST_DATABASE", "boardfactory_test").strip()
    if not test_db:
        test_db = "boardfactory_test"
    _ensure_test_database(test_db)
    test_url = _swap_database_name(_runtime_database_url(), test_db)

    # Migrate the test DB to head exactly once per session.
    import infrastructure.db as storage_db

    storage_db.dispose_engine()
    storage_db.override_database_url(test_url)

    from alembic import command
    from alembic.config import Config

    ini_path = _APP_ROOT / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(_APP_ROOT / "migrations"))
    command.upgrade(cfg, "head")

    yield test_url

    storage_db.dispose_engine()
    storage_db.override_database_url(None)


@pytest.fixture(autouse=True)
def isolated_repo(tmp_path, monkeypatch, _test_database_url):
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
    monkeypatch.setenv("BOARDFACTORY_DATABASE_URL", _test_database_url)
    monkeypatch.setenv("BOARDFACTORY_BOARDS_DIR", str(repo / "data" / "boards"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PIXELLAB_API_KEY", raising=False)

    # Drop any cached BoardStore from a previous test before any code
    # under test has a chance to call ``get_store()`` against the stale
    # singleton.
    from infrastructure import board_store as _bs

    _bs.reset_store()

    # Pin infrastructure.db at the test DB and wipe all table contents so each
    # test starts with an empty schema (no per-test migrations needed).
    import infrastructure.db as storage_db

    storage_db.dispose_engine()
    storage_db.override_database_url(_test_database_url)
    storage_db.get_engine()

    _truncate_all_tables()

    # Some modules cache REPO_ROOT at import time. Reload them so the
    # fixture's monkeypatched env wins for the duration of the test.
    import importlib

    for mod_name in (
        "boardfactory.config",
        "boardfactory",
        "auth.users",
        "jobs.cost_ledger",
        "auth.sessions",
        "infrastructure.db",
    ):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            importlib.reload(mod)

    # infrastructure.db was reloaded above; rebind the override on the *new*
    # module object so every caller resolves to the test DB.
    import infrastructure.db as storage_db

    storage_db.override_database_url(_test_database_url)

    from boardfactory import config as _bf_config
    from domains.boards import repository as boards_repo

    _bf_config.set_board_root_resolver(boards_repo.store_board_root)

    # ``infrastructure.board_store`` is _not_ reloaded — reloading would create
    # a fresh ``_store`` module-level slot but other modules already hold
    # a reference to the old module's ``get_store`` / ``reset_store``
    # functions. We instead drop the singleton in-place via reset_store()
    # at the start of the fixture.

    yield repo

    # tmp_path is auto-cleaned by pytest; this is just defensive.
    shutil.rmtree(repo, ignore_errors=True)


@pytest.fixture
def db_engine(isolated_repo):
    """A clean SQLAlchemy engine pointing at the session-scoped test DB."""
    from infrastructure import db as storage_db

    yield storage_db.get_engine()


@pytest.fixture
def path_slug() -> str:
    return "test-board"


@pytest.fixture
def board_id(seeded_board):
    return seeded_board.id


@pytest.fixture
def test_user(isolated_repo):
    """Single test account (fresh DB allows first-user registration)."""
    from auth import services as auth_services

    return auth_services.create_first_user(
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

    from domains.boards import services as bd
    from domains.boards import repository as bo
    from infrastructure import board_store as bs

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

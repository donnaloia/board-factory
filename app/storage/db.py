"""SQLAlchemy engine + session factory.

Creates no tables by itself — **Alembic** applies DDL (see ``app/migrations/``).
Callers use ``session_scope()`` for request-scoped work.

URL resolution (first match wins unless tests override):

* ``BOARDFACTORY_DATABASE_URL`` if set (e.g. ``postgresql+psycopg://…`` in Docker).
* Else SQLite at ``BOARDFACTORY_DB_PATH``, defaulting to
  ``<BOARDFACTORY_REPO>/.boardfactory.db``.

Notes:

* **Single process-wide engine**, lazy-init. Tests use ``override_database_url``.
* **SQLite:** foreign keys ON, WAL journal mode, ``check_same_thread=False``
  for FastAPI’s thread pool.
* ORM models live in ``storage/models/``; import ``storage.db`` for the engine.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
DEFAULT_DB_PATH = REPO_ROOT / ".boardfactory.db"


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_lock = RLock()
_override_url: str | None = None


def _resolve_database_url() -> str:
    """Build the SQLAlchemy URL from env / overrides."""
    if _override_url is not None:
        return _override_url
    explicit = os.environ.get("BOARDFACTORY_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    db_path = Path(os.environ.get("BOARDFACTORY_DB_PATH", str(DEFAULT_DB_PATH)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


def override_database_url(url: str | None) -> None:
    """Test hook: force every subsequent caller to use ``url``.

    Call with ``None`` to revert to env-driven resolution. Resets the cached
    engine so the next ``get_engine()`` rebuilds it.
    """
    global _override_url, _engine, _SessionLocal
    with _lock:
        _override_url = url
        _engine = None
        _SessionLocal = None


def _build_engine(url: str) -> Engine:
    connect_args: dict = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        # ``check_same_thread`` defaults to True for SQLite; we share the
        # engine across threads (FastAPI threadpool) so we have to relax it.
        # Concurrency is still correct because each ``Session`` lives on
        # exactly one thread for the duration of a request/job.
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
    )

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
            # Foreign keys aren't on by default in SQLite. WAL gives us
            # concurrent readers without blocking the writer.
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
            finally:
                cursor.close()

    return engine


def get_engine() -> Engine:
    """Return the process-wide engine, building it on first use."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            url = _resolve_database_url()
            _engine = _build_engine(url)
            _SessionLocal = sessionmaker(
                bind=_engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                future=True,
            )
    return _engine


def session_factory() -> sessionmaker[Session]:
    """Return the session factory, ensuring the engine is initialised."""
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None  # mypy / safety
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager: yields a ``Session``, commits on success, rolls back on error.

    Usage::

        with session_scope() as session:
            session.add(...)
            ...
    """
    factory = session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Tear down the engine. Mostly for tests that need a clean slate."""
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None

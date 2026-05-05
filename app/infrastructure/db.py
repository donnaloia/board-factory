"""SQLAlchemy engine + session factory.

Creates no tables by itself — **Alembic** applies DDL (see ``app/migrations/``).
Callers use ``session_scope()`` for request-scoped work.

URL resolution:

* ``BOARDFACTORY_DATABASE_URL`` is required (e.g. ``postgresql+psycopg://…``).
  The compose stack sets this on the ``board-factory`` service. Tests use
  ``override_database_url`` to point at a session-scoped test database.

Postgres is the only supported backend. The runtime previously fell back to
a local SQLite file for portable checkouts, but every deploy and dev workflow
now uses the ``postgres`` compose service.

Notes:

* **Single process-wide engine**, lazy-init. Tests use ``override_database_url``.
* ORM models live in ``app/models/``; import ``infrastructure.db`` for the engine.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from threading import RLock
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_lock = RLock()
_override_url: str | None = None


def _resolve_database_url() -> str:
    """Return the SQLAlchemy URL, raising if neither override nor env is set."""
    if _override_url is not None:
        return _override_url
    explicit = os.environ.get("BOARDFACTORY_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    raise RuntimeError(
        "BOARDFACTORY_DATABASE_URL is not set. The app requires a Postgres URL "
        "(e.g. ``postgresql+psycopg://user:pass@host:5432/db``); the legacy "
        "SQLite fallback was removed."
    )


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
    return create_engine(url, future=True, pool_pre_ping=True)


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

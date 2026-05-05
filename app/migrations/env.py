"""Alembic environment for the Board Factory web application.

Uses the same URL resolver as ``infrastructure.db`` so CLI migrations and the running
app never point at different databases.

``target_metadata`` is ``None``: revisions are **hand-written** (not
``alembic revision --autogenerate`` from SQLAlchemy metadata). Keep models and
migrations in sync by convention.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

try:
    from infrastructure.db import _resolve_database_url
except Exception:  # pragma: no cover
    _resolve_database_url = None


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _configured_url():
    if _resolve_database_url is not None:
        return _resolve_database_url()
    raw = config.get_main_option("sqlalchemy.url") or ""
    if not raw:
        raise RuntimeError(
            "No database URL configured. Set BOARDFACTORY_DATABASE_URL, "
            "or run alembic from the ``app/`` package so infrastructure.db is importable."
        )
    return raw


def run_migrations_offline():
    url = _configured_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _configured_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

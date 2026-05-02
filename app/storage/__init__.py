"""Storage layer for the Board Factory web application.

  - ``db`` — SQLAlchemy engine, ``session_scope``, and URL resolution shared
    with Alembic.

  - ``fs`` — filesystem helpers for ``boards/<id>/`` (paths, YAML, workspace
    layout).

  - ``models`` — ORM table definitions (imported by services and migrations).

Callers pass ``board_id`` explicitly where possible; the pipeline still uses a
thread-local active board inside ``boardfactory.config`` for job-scoped paths.
"""

__all__ = ["db", "fs"]

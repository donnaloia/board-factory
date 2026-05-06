"""Storage layer for the Board Factory web application.

This package owns the I/O boundaries: SQL connections, the per-board file
store, and shared filesystem path math. The shared SQLAlchemy
``DeclarativeBase`` lives in ``infrastructure.orm``; each domain's table
mappings live in that domain's ``models.py``.

  - ``board_store`` — the ``BoardStore`` protocol + ``LocalBoardStore``
    backend. Singleton wired in via ``get_store()``; every per-board file
    read/write goes through it.

  - ``db`` — SQLAlchemy engine, ``session_scope``, and URL resolution
    shared with Alembic.

  - ``deps`` — Shared FastAPI ``Depends`` helpers and HTTP glue (nested board
    resolution, ``job_or_redirect_response``, ``editorial_template_context``, …).

  - ``fs`` — filesystem path helpers that delegate to the configured
    ``BoardStore`` (e.g. ``fs.workspace.live_path``). Use the bytes API on
    the store directly for backend-agnostic operations.

Callers pass ``board_id`` explicitly where possible; the pipeline still
uses a thread-local active board inside ``boardfactory.config`` for
job-scoped paths.
"""

__all__ = ["board_store", "db", "fs"]

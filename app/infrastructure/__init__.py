"""Storage layer for the Board Factory web application.

This package owns the I/O boundaries: SQL connections, the per-board file
store, and shared filesystem path math. Domain ORM models live one level
up at ``app/models/`` so they sit alongside the rest of the application
surface (services, routes) rather than being buried inside infrastructure.

  - ``board_store`` — the ``BoardStore`` protocol + ``LocalBoardStore``
    backend. Singleton wired in via ``get_store()``; every per-board file
    read/write goes through it.

  - ``db`` — SQLAlchemy engine, ``session_scope``, and URL resolution
    shared with Alembic.

  - ``fs`` — filesystem path helpers that delegate to the configured
    ``BoardStore`` (e.g. ``fs.workspace.live_path``). Use the bytes API on
    the store directly for backend-agnostic operations.

Callers pass ``board_id`` explicitly where possible; the pipeline still
uses a thread-local active board inside ``boardfactory.config`` for
job-scoped paths.
"""

__all__ = ["board_store", "db", "fs"]

"""Workspace paths and configuration constants — multi-board scoped.

Each Board Factory project ("board") owns a self-contained directory tree
under the configured per-board data root (``data/boards/<id>/`` by default,
overridable via ``BOARDFACTORY_BOARDS_DIR``):

    <store-root>/<board-id>/
        workspace/
            style/        # palette + style sheet (cheap, local)
            history/      # every generated version, per cell, with sidecars
            live/         # current promoted asset per cell
            preview/      # composited board_idle / board_active
            logs/
            frames/       # 9-slice house frame for functional panels
        mockup/
        export/           # engine-ready tiles + manifest (Export step output)

The pipeline package always reads/writes the local filesystem at this root.
The web app uses the same root via the ``BoardStore`` abstraction in
``app/storage/board_store.py``; both pick up ``BOARDFACTORY_BOARDS_DIR`` so
they stay in sync.

The board **catalog spec** lives in the application database; ``catalog.yml``
is optional legacy-only. ``config.CATALOG_PATH`` still resolves for rare
tools that open a path.

The **active board id is stored per OS thread** (``threading.local()``).
Paths resolved via ``config.WORKSPACE`` et al. always reflect that thread's
active board, which lets the JobRunner process concurrent jobs on different
boards.

``scope_board(board_id)`` acquires a **per-board re-entrant lock** so two
threads never mutate the same board workspace simultaneously; unrelated
boards can run in parallel.

Legacy CLI-era directories (``workspace/candidates/``, ``cleaned/``,
``approved/``) are not exposed on ``config`` anymore and are no longer read
by anything; the migration that seeded ``live/`` from old ``approved/``
trees was removed once all known checkouts had been migrated.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def _boards_dir() -> Path:
    """Resolve the per-board data root the same way the app's BoardStore does.

    Order of precedence:

      1. ``BOARDFACTORY_BOARDS_DIR`` (absolute path) — full override.
      2. ``<BOARDFACTORY_REPO>/data/boards`` — current default.

    Resolved at call time so tests that monkey-patch the env see updates.
    """
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return REPO_ROOT / "data" / "boards"


# Backward-compat: ``BOARDS_DIR`` is referenced as a module attribute by
# older callers. Resolved lazily through PEP 562 ``__getattr__`` below so
# environment changes (e.g. tests) take effect.


# ────────────────────────── pipeline knobs (board-independent) ──────────────────────────


PALETTE_SIZE = int(os.environ.get("BOARDFACTORY_PALETTE_SIZE", "24"))
SPACE_CANDIDATES = int(os.environ.get("BOARDFACTORY_SPACE_CANDIDATES", "3"))
PANEL_CANDIDATES = int(os.environ.get("BOARDFACTORY_PANEL_CANDIDATES", "6"))
CENTERPIECE_CANDIDATES = int(os.environ.get("BOARDFACTORY_CENTERPIECE_CANDIDATES", "12"))

PROJECT_NAME = os.environ.get("BOARDFACTORY_PROJECT_NAME", "my-board")
PROVIDER_NAME = os.environ.get("BOARDFACTORY_PROVIDER", "pixellab").lower()


# ────────────────────────── board scope ──────────────────────────


_tls = threading.local()

_board_locks: dict[str, RLock] = {}
_board_locks_guard = RLock()


def _lock_for_board(board_id: str) -> RLock:
    with _board_locks_guard:
        lk = _board_locks.get(board_id)
        if lk is None:
            lk = RLock()
            _board_locks[board_id] = lk
        return lk


def set_board(board_id: str | None) -> None:
    """Assign ``board_id`` as this thread's active board (``None`` clears)."""
    if board_id is None:
        if hasattr(_tls, "board_id"):
            del _tls.board_id
    else:
        _tls.board_id = board_id


def active_board() -> str | None:
    return getattr(_tls, "board_id", None)


def board_root(board_id: str | None = None) -> Path:
    """Return the root dir for a board. Defaults to the active board."""
    bid = board_id or active_board()
    if not bid:
        raise RuntimeError(
            "No active board set. Call config.set_board(board_id) first, "
            "or pass board_id explicitly."
        )
    return _boards_dir() / bid


# ────────────────────────── path properties ──────────────────────────


# Map of attribute-style path names to their layout under <store-root>/<id>/.
# Resolved lazily via PEP 562 module __getattr__ so each access reflects
# the currently active board id.
_PATH_LAYOUT: dict[str, tuple[str, ...]] = {
    "BOARD_ROOT":      (),
    "CATALOG_PATH":    ("catalog.yml",),
    "MOCKUP_DIR":      ("mockup",),
    "WORKSPACE":       ("workspace",),
    "STYLE_DIR":       ("workspace", "style"),
    "PREVIEW_DIR":     ("workspace", "preview"),
    "LOGS_DIR":        ("workspace", "logs"),
    "HISTORY_DIR":     ("workspace", "history"),
    "LIVE_DIR":        ("workspace", "live"),
    "EXPORT_DIR":      ("export",),
}


def __getattr__(name: str) -> Path:
    """Resolve path attributes lazily so they always reflect the active board.

    ``BOARDS_DIR`` resolves through ``_boards_dir()`` so env tweaks (the
    ``BOARDFACTORY_BOARDS_DIR`` override, or a different repo root in
    tests) are picked up without needing to reload the module.
    """
    if name == "BOARDS_DIR":
        return _boards_dir()
    parts = _PATH_LAYOUT.get(name)
    if parts is None:
        raise AttributeError(f"module 'boardfactory.config' has no attribute {name!r}")
    return board_root().joinpath(*parts)


# ────────────────────────── filesystem bootstrap ──────────────────────────


def ensure_dirs() -> None:
    """Create every workspace subdir the web pipeline writes to."""
    root = board_root()
    for name in (
        "STYLE_DIR", "PREVIEW_DIR", "LOGS_DIR",
        "HISTORY_DIR", "LIVE_DIR", "EXPORT_DIR", "MOCKUP_DIR",
    ):
        root.joinpath(*_PATH_LAYOUT[name]).mkdir(parents=True, exist_ok=True)


# ────────────────────────── per-request scope helpers ──────────────────────────


@contextmanager
def scope_board(board_id: str):
    """Serialize same-board *mutations* (write side).

    Acquires the per-board re-entrant lock and pins the thread-local active
    board for the duration. Use for anything that *mutates* per-board state
    (a pipeline job, ``promote()``, frame adoption, mockup upload) so two
    workers can't trample each other on the same board. Other boards stay
    free to proceed concurrently.

    For read-only operations that only need path resolution (history listing,
    "is the frame adopted?", side-panel hydration), prefer
    ``set_active_board()`` — it sets the thread-local without taking the
    lock, so a side-panel fetch never queues behind a long-running provider
    call for the same board.
    """
    lock = _lock_for_board(board_id)
    with lock:
        prev = active_board()
        set_board(board_id)
        try:
            yield
        finally:
            set_board(prev)


@contextmanager
def set_active_board(board_id: str):
    """Pin ``board_id`` as this thread's active board for the duration.

    Read-only counterpart to ``scope_board()``: same thread-local effect,
    no lock acquisition. Pure read paths (e.g. ``bf_assets.list_history``,
    the side-panel fetch) should use this so they never block on a writer
    holding the per-board lock.
    """
    prev = active_board()
    set_board(board_id)
    try:
        yield
    finally:
        set_board(prev)

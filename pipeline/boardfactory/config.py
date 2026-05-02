"""Workspace paths and configuration constants — multi-board scoped.

Each Board Factory project ("board") owns a self-contained directory tree:

    boards/<board-id>/
        workspace/
            style/        # palette + style sheet (cheap, local)
            history/      # every generated version, per cell, with sidecars
            live/         # current promoted asset per cell
            preview/      # composited board_idle / board_active
            refinements/  # centerpiece masked-inpaint outputs
            logs/
            frames/       # 9-slice house frame for functional panels
        mockup/
        export/           # engine-ready tiles + manifest (Export step output)

The board **catalog spec** lives in the application database; ``catalog.yml`` is
optional legacy-only. ``config.CATALOG_PATH`` still resolves for rare tools that
open a path.

The **active board id is stored per OS thread** (``threading.local()``). Paths
resolved via ``config.WORKSPACE`` et al. always reflect that thread's active
board, which lets the JobRunner process concurrent jobs on different boards.

``scope_board(board_id)`` acquires a **per-board re-entrant lock** so two
threads never mutate the same board workspace simultaneously; unrelated boards
can run in parallel (Phase 5).

Legacy CLI-era directories (`workspace/candidates/`, ``cleaned/``, ``approved/``)
are not exposed on ``config`` anymore. One-time migration reads them via
``WORKSPACE / "approved" / …`` inside ``boardfactory.assets``; the web app
startup skips that work unless those trees still exist on disk.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
BOARDS_DIR = REPO_ROOT / "boards"


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
    return BOARDS_DIR / bid


# ────────────────────────── path properties ──────────────────────────


# Map of attribute-style path names to their layout under boards/<id>/.
# Resolved lazily via PEP 562 module __getattr__ so each access reflects
# the currently active board id.
_PATH_LAYOUT: dict[str, tuple[str, ...]] = {
    "BOARD_ROOT":      (),
    "CATALOG_PATH":    ("catalog.yml",),
    "MOCKUP_DIR":      ("mockup",),
    "WORKSPACE":       ("workspace",),
    "STYLE_DIR":       ("workspace", "style"),
    "REFINEMENTS_DIR": ("workspace", "refinements"),
    "PREVIEW_DIR":     ("workspace", "preview"),
    "LOGS_DIR":        ("workspace", "logs"),
    "HISTORY_DIR":     ("workspace", "history"),
    "LIVE_DIR":        ("workspace", "live"),
    "EXPORT_DIR":      ("export",),
}


def __getattr__(name: str) -> Path:
    """Resolve path attributes lazily so they always reflect the active board."""
    parts = _PATH_LAYOUT.get(name)
    if parts is None:
        raise AttributeError(f"module 'boardfactory.config' has no attribute {name!r}")
    return board_root().joinpath(*parts)


# ────────────────────────── filesystem bootstrap ──────────────────────────


def ensure_dirs() -> None:
    """Create every workspace subdir the web pipeline writes to."""
    root = board_root()
    for name in (
        "STYLE_DIR", "REFINEMENTS_DIR", "PREVIEW_DIR", "LOGS_DIR",
        "HISTORY_DIR", "LIVE_DIR", "EXPORT_DIR", "MOCKUP_DIR",
    ):
        root.joinpath(*_PATH_LAYOUT[name]).mkdir(parents=True, exist_ok=True)


# ────────────────────────── per-request scope helper ──────────────────────────


@contextmanager
def scope_board(board_id: str):
    """Serialize same-board work; other boards may proceed concurrently."""
    lock = _lock_for_board(board_id)
    with lock:
        prev = active_board()
        set_board(board_id)
        try:
            yield
        finally:
            set_board(prev)

"""Workspace paths and configuration constants — multi-board scoped.

Each Board Factory project ("board") owns a self-contained directory tree:

    boards/<board-id>/
        catalog.yml
        workspace/
            style/        # palette + style sheet (cheap, local)
            history/      # every generated version, per cell, with sidecars
            live/         # current promoted asset per cell
            preview/      # composited board_idle / board_active
            refinements/  # centerpiece masked-inpaint outputs
            logs/
            frames/       # 9-slice house frame for functional panels
        mockup/
        board_assets/     # exported tiles + manifest for the engine

The active board id is held as module-level mutable state so every existing
`config.WORKSPACE`-style access keeps working without threading a board id
through every call site. The web app calls `set_board()` per request via
`scope_board()`.

Legacy paths (`candidates/`, `cleaned/`, `approved/`) are still resolvable
so the boot-time migration can read them, but `ensure_dirs()` no longer
creates them — once migrated, they're deleted and never come back.

Threading note: this is process-global state. The web app holds a lock around
each request to serialize board-scoped work. Acceptable because all expensive
operations are offloaded to the JobRunner thread pool, not the request handler.
"""

from __future__ import annotations

import os
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


_lock = RLock()
_active_board: str | None = None


def set_board(board_id: str | None) -> None:
    """Set the active board id. Pass None to clear (rare)."""
    global _active_board
    with _lock:
        _active_board = board_id


def active_board() -> str | None:
    return _active_board


def board_root(board_id: str | None = None) -> Path:
    """Return the root dir for a board. Defaults to the active board."""
    bid = board_id or _active_board
    if not bid:
        raise RuntimeError(
            "No active board set. Call config.set_board(board_id) first, "
            "or pass board_id explicitly."
        )
    return BOARDS_DIR / bid


# ────────────────────────── path properties (compat layer) ──────────────────────────
#
# Existing code does `config.WORKSPACE`, `config.STYLE_DIR`, etc. These were
# module attributes before; now they're computed properties via __getattr__
# so they always reflect the currently-active board.


def _path_for(name: str) -> Path:
    """Resolve a board-scoped path by symbolic name."""
    root = board_root()
    return {
        "BOARD_ROOT":     root,
        "CATALOG_PATH":   root / "catalog.yml",
        "MOCKUP_DIR":     root / "mockup",
        "WORKSPACE":      root / "workspace",
        "STYLE_DIR":      root / "workspace" / "style",
        "CANDIDATES_DIR": root / "workspace" / "candidates",
        "CLEANED_DIR":    root / "workspace" / "cleaned",
        "APPROVED_DIR":   root / "workspace" / "approved",
        "REFINEMENTS_DIR":root / "workspace" / "refinements",
        "PREVIEW_DIR":    root / "workspace" / "preview",
        "LOGS_DIR":       root / "workspace" / "logs",
        "HISTORY_DIR":    root / "workspace" / "history",
        "LIVE_DIR":       root / "workspace" / "live",
        "EXPORT_DIR":     root / "board_assets",
    }[name]


_PATH_NAMES = {
    "BOARD_ROOT", "CATALOG_PATH", "MOCKUP_DIR", "WORKSPACE", "STYLE_DIR",
    "CANDIDATES_DIR", "CLEANED_DIR", "APPROVED_DIR", "REFINEMENTS_DIR",
    "PREVIEW_DIR", "LOGS_DIR", "HISTORY_DIR", "LIVE_DIR", "EXPORT_DIR",
}


def __getattr__(name: str) -> Path:
    """Resolve path attributes lazily so they always reflect the active board.

    This is only called for attributes not found in the module's normal
    namespace, so the constants above (PALETTE_SIZE etc.) are unaffected.
    """
    if name in _PATH_NAMES:
        return _path_for(name)
    raise AttributeError(f"module 'boardfactory.config' has no attribute {name!r}")


# ────────────────────────── filesystem bootstrap ──────────────────────────


def ensure_dirs() -> None:
    """Create every workspace subdir the web pipeline writes to.

    Note: the legacy CLI working dirs (`candidates/`, `cleaned/`, `approved/`)
    are intentionally not pre-created. They are read by the boot-time
    migration if they happen to exist (carrying old assets that need
    seeding into live/ + history/) and otherwise never recreated.
    """
    for name in (
        "STYLE_DIR", "REFINEMENTS_DIR", "PREVIEW_DIR", "LOGS_DIR",
        "HISTORY_DIR", "LIVE_DIR", "EXPORT_DIR", "MOCKUP_DIR",
    ):
        _path_for(name).mkdir(parents=True, exist_ok=True)


# ────────────────────────── per-request scope helper ──────────────────────────


from contextlib import contextmanager


@contextmanager
def scope_board(board_id: str):
    """Set the active board for the duration of a block, restore after.

    Used by the web app to scope each request to one board. Holds the global
    lock so concurrent requests for different boards don't trample each other.
    Acceptable because actual work is offloaded to the JobRunner thread pool.
    """
    with _lock:
        prev = _active_board
        set_board(board_id)
        try:
            yield
        finally:
            set_board(prev)

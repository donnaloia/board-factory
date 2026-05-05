"""Filesystem layout for board workspaces — thin wrappers over ``BoardStore``.

Single source of truth for every path under ``<board-store-root>/<id>/``.
Routes and the service layer import these helpers instead of duplicating
path math. Internally each helper resolves paths through the configured
``BoardStore`` so the same code works against local disk today and an
object store later.

Two design rules:

1. **No HTTP types.** Functions raise ``ValueError`` / ``FileNotFoundError``
   on misuse so this module can be reused from CLI / tests / pipeline
   without dragging FastAPI in.

2. **Resolve store at call time.** The ``BoardStore`` singleton is fetched
   on every call (cheap — ``get_store()`` returns a cached instance) so
   tests that swap the store via ``override_store`` see the change
   immediately, without touching every caller.

The functions returning ``Path`` work only against the local backend; for
true backend-agnostic operations use the byte methods on the store
directly (``store.read_bytes``, ``store.write_bytes``, …).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from infrastructure.board_store import BoardStore, LocalBoardStore, get_store

# ────────────────────────── repo / boards roots ──────────────────────────


def repo_root() -> Path:
    return Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def _local_store() -> LocalBoardStore:
    """Return the configured store, asserting it's the local backend.

    Helpers that return ``Path`` only make sense for ``LocalBoardStore``.
    The bytes-shaped operations on the store itself work for any backend.
    """
    store: BoardStore = get_store()
    if not isinstance(store, LocalBoardStore):
        raise RuntimeError(
            "infrastructure.files.workspace path helpers require a LocalBoardStore "
            f"backend; got {type(store).__name__}. Use the bytes API on "
            "the store directly for backend-agnostic operations."
        )
    return store


def boards_dir() -> Path:
    return _local_store()._root  # type: ignore[attr-defined]


def board_root(board_id: str) -> Path:
    return _local_store().board_root(board_id)


def export_dir(board_id: str) -> Path:
    """Engine-ready tiles + ``board_manifest.json`` from the Export pipeline step."""
    return _local_store().local_path(board_id, "export")


def workspace_dir(board_id: str) -> Path:
    return _local_store().local_path(board_id, "workspace")


def style_dir(board_id: str) -> Path:
    return _local_store().local_path(board_id, "workspace/style")


def palette_json_path(board_id: str) -> Path:
    return _local_store().local_path(board_id, "workspace/style/palette.json")


def mockup_dir(board_id: str) -> Path:
    return _local_store().local_path(board_id, "mockup")


def default_mockup_path(board_id: str) -> Path:
    return _local_store().local_path(board_id, "mockup/board.png")


# ────────────────────────── per-cell paths ──────────────────────────


def live_rel(category: str, asset_id: str) -> str:
    """Forward-slash rel-path of the promoted PNG for one cell.

    Centerpiece has a fixed filename (the catalog only ever has one).
    Backend-agnostic — usable with ``store.read_bytes(board_id, live_rel(...))``.
    """
    if category == "centerpiece":
        return "workspace/live/centerpiece/centerpiece.png"
    return f"workspace/live/{category}/{asset_id}.png"


def live_source_rel(category: str, asset_id: str) -> str:
    """JSON pointer: which history file was last promoted to live (see ``live_prompt``)."""
    return f"workspace/meta/live_source/{category}/{asset_id}.json"


def live_path(board_id: str, category: str, asset_id: str) -> Path:
    """Promoted PNG for one cell. Local-only; for S3 use ``live_rel`` + the store."""
    return _local_store().local_path(board_id, live_rel(category, asset_id))


def history_rel(category: str, asset_id: str) -> str:
    return f"workspace/history/{category}/{asset_id}"


def history_dir(board_id: str, category: str, asset_id: str) -> Path:
    return _local_store().local_path(board_id, history_rel(category, asset_id))


# ────────────────────────── safe path resolution ──────────────────────────


class PathTraversalError(ValueError):
    """Raised when a workspace-relative path tries to escape the workspace."""


def safe_workspace_relative(board_id: str, rel: str) -> Path:
    """Resolve ``rel`` underneath ``workspace_dir(board_id)``.

    Raises ``PathTraversalError`` if the resolved path lives outside the
    workspace (e.g. ``../../etc/passwd``).
    """
    ws = workspace_dir(board_id).resolve()
    target = (ws / rel).resolve()
    if not str(target).startswith(str(ws)):
        raise PathTraversalError(f"{rel!r} resolves outside the workspace")
    return target


# ────────────────────────── readiness checks ──────────────────────────


def has_palette(board_id: str) -> bool:
    return get_store().exists(board_id, "workspace/style/palette.json")


def read_palette(board_id: str) -> list[tuple[int, int, int]] | None:
    """Return the cleanup palette as a list of RGB tuples, or ``None`` if absent."""
    store = get_store()
    if not store.exists(board_id, "workspace/style/palette.json"):
        return None
    raw = store.read_bytes(board_id, "workspace/style/palette.json")
    return [tuple(c) for c in json.loads(raw.decode("utf-8"))]


def resolve_mockup_path(board_id: str, catalog: dict | None) -> Path:
    """Return the absolute mockup path implied by ``catalog.style.reference_image``.

    Falls back to the default ``mockup/board.png`` when the catalog is
    missing or doesn't override the reference. Existence is *not* checked
    here - callers decide how to handle a missing file. Local-only.
    """
    rel = mockup_relpath(catalog)
    return _local_store().local_path(board_id, rel)


def mockup_relpath(catalog: dict | None) -> str:
    """Return the catalog-declared relative path string for templates."""
    rel = "mockup/board.png"
    if isinstance(catalog, dict):
        style = catalog.get("style") or {}
        if isinstance(style, dict) and isinstance(style.get("reference_image"), str):
            rel = style["reference_image"]
    return rel


# ────────────────────────── listings ──────────────────────────


def list_history_pngs(board_id: str, category: str, asset_id: str) -> list[Path]:
    """Sorted list of history PNGs for one cell. Local-only."""
    d = history_dir(board_id, category, asset_id)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.png"))

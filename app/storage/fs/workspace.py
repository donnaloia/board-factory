"""Filesystem layout for board workspaces.

Single source of truth for every path under ``boards/<id>/``. Routes and the
service layer import these helpers instead of duplicating path math.

Two design rules:

1. **No HTTP types.** Functions raise ``ValueError`` / ``FileNotFoundError``
   on misuse so this module can be reused from CLI / tests / pipeline
   without dragging FastAPI in.
2. **Resolve env at call time.** ``BOARDFACTORY_REPO`` is read on every
   call rather than cached at import, which makes tests that monkey-patch
   the env behave correctly. (The pipeline package still caches ``REPO_ROOT``
   at import for backward compatibility.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ────────────────────────── repo / boards roots ──────────────────────────


def repo_root() -> Path:
    return Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def boards_dir() -> Path:
    return repo_root() / "boards"


def board_root(board_id: str) -> Path:
    return boards_dir() / board_id


def export_dir(board_id: str) -> Path:
    """Engine-ready tiles + ``board_manifest.json`` from the Export pipeline step."""
    return board_root(board_id) / "export"


def migrate_legacy_board_assets_to_export(board_id: str) -> None:
    """Rename ``board_assets/`` → ``export/`` when the legacy name is still on disk."""
    legacy = board_root(board_id) / "board_assets"
    target = export_dir(board_id)
    if legacy.exists() and not target.exists():
        try:
            legacy.rename(target)
        except OSError:
            pass


def migrate_all_legacy_board_assets_to_export() -> None:
    root = boards_dir()
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            try:
                migrate_legacy_board_assets_to_export(child.name)
            except OSError:
                continue


def catalog_path(board_id: str) -> Path:
    return board_root(board_id) / "catalog.yml"


def workspace_dir(board_id: str) -> Path:
    return board_root(board_id) / "workspace"


def style_dir(board_id: str) -> Path:
    return workspace_dir(board_id) / "style"


def palette_json_path(board_id: str) -> Path:
    return style_dir(board_id) / "palette.json"


def mockup_dir(board_id: str) -> Path:
    return board_root(board_id) / "mockup"


def default_mockup_path(board_id: str) -> Path:
    return mockup_dir(board_id) / "board.png"


# ────────────────────────── per-cell paths ──────────────────────────


def live_path(board_id: str, category: str, asset_id: str) -> Path:
    """Promoted PNG for one cell. Centerpiece has a fixed filename."""
    if category == "centerpiece":
        return workspace_dir(board_id) / "live" / "centerpiece" / "centerpiece.png"
    return workspace_dir(board_id) / "live" / category / f"{asset_id}.png"


def history_dir(board_id: str, category: str, asset_id: str) -> Path:
    return workspace_dir(board_id) / "history" / category / asset_id


def approved_path_legacy(board_id: str, category: str, asset_id: str) -> Path:
    """Legacy CLI-era path; read-only at this point - migration code seeds
    these into ``live/`` + ``history/`` and then ``purge_legacy_dirs()``
    removes them.
    """
    if category == "centerpiece":
        return workspace_dir(board_id) / "approved" / "centerpiece.png"
    return workspace_dir(board_id) / "approved" / category / f"{asset_id}.png"


def legacy_cli_workspace_trees_exist(board_id: str) -> bool:
    """True if any legacy CLI staging directory is still present under ``workspace/``.

    Boot-time seed/purge skips boards when this is false so normal servers do
    not scan every cell on every startup.
    """
    ws = workspace_dir(board_id)
    return any((ws / name).exists() for name in ("candidates", "cleaned", "approved"))


def cleaned_dir_legacy(board_id: str, category: str, asset_id: str | None = None) -> Path:
    base = workspace_dir(board_id) / "cleaned" / category
    return base / asset_id if asset_id else base


def candidates_dir_legacy(board_id: str, category: str, asset_id: str | None = None) -> Path:
    base = workspace_dir(board_id) / "candidates" / category
    return base / asset_id if asset_id else base


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
    return palette_json_path(board_id).exists()


def read_palette(board_id: str) -> list[tuple[int, int, int]] | None:
    """Return the cleanup palette as a list of RGB tuples, or ``None`` if absent."""
    p = palette_json_path(board_id)
    if not p.exists():
        return None
    return [tuple(c) for c in json.loads(p.read_text())]


def resolve_mockup_path(board_id: str, catalog: dict | None) -> Path:
    """Return the absolute mockup path implied by ``catalog.style.reference_image``.

    Falls back to the default ``mockup/board.png`` when the catalog is
    missing or doesn't override the reference. Existence is *not* checked
    here - callers decide how to handle a missing file.
    """
    rel = "mockup/board.png"
    if isinstance(catalog, dict):
        style = catalog.get("style") or {}
        if isinstance(style, dict) and isinstance(style.get("reference_image"), str):
            rel = style["reference_image"]
    return board_root(board_id) / rel


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
    d = history_dir(board_id, category, asset_id)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.png"))


def list_legacy_cleaned(
    board_id: str, category: str, asset_id: str | None = None
) -> list[Path]:
    base = cleaned_dir_legacy(board_id, category, asset_id)
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.png") if not p.name.startswith("_"))


def list_legacy_raw_candidates(
    board_id: str, category: str, asset_id: str | None = None
) -> list[Path]:
    base = candidates_dir_legacy(board_id, category, asset_id)
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.png") if not p.name.startswith("_"))

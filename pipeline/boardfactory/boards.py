"""Multi-board registry — list, create, rename boards on disk.

Each board is a self-contained directory under boards/. The id is the
directory name (slug) and is what URLs and the CLI use. The display name
is the `project` field in catalog.yml, which the user can edit freely.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config


@dataclass(frozen=True)
class BoardInfo:
    id: str                # slug, e.g. "damnation"
    project: str           # display name from catalog.yml, e.g. "damnation-board"
    catalog_path: Path     # boards/<id>/catalog.yml
    has_catalog: bool
    has_mockup: bool


# ────────────────────────── slug ──────────────────────────


_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def slugify(name: str) -> str:
    """Turn a free-form name into a valid board id.

    Lowercase, ASCII alphanumerics + '-' / '_'. Collapses runs of separators,
    trims to 64 chars. Returns 'untitled' if the input boils down to nothing.
    """
    if not name:
        return "untitled"
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    if not s:
        return "untitled"
    return s[:64]


def is_valid_id(board_id: str) -> bool:
    return bool(_SLUG_OK.match(board_id))


# ────────────────────────── list / read ──────────────────────────


def list_boards() -> list[BoardInfo]:
    """Return every board on disk, sorted alphabetically by id."""
    if not config.BOARDS_DIR.exists():
        return []
    boards: list[BoardInfo] = []
    for child in sorted(config.BOARDS_DIR.iterdir()):
        if not child.is_dir():
            continue
        if not is_valid_id(child.name):
            continue
        boards.append(_load_board_info(child.name))
    return boards


def get_board(board_id: str) -> BoardInfo | None:
    if not is_valid_id(board_id):
        return None
    root = config.BOARDS_DIR / board_id
    if not root.exists() or not root.is_dir():
        return None
    return _load_board_info(board_id)


def _load_board_info(board_id: str) -> BoardInfo:
    root = config.BOARDS_DIR / board_id
    cat_path = root / "catalog.yml"
    project = board_id
    has_catalog = cat_path.exists()
    if has_catalog:
        try:
            with cat_path.open() as f:
                data = yaml.safe_load(f) or {}
            project = data.get("project") or board_id
        except Exception:
            pass
    has_mockup = (root / "mockup").exists() and any((root / "mockup").iterdir())
    return BoardInfo(
        id=board_id,
        project=project,
        catalog_path=cat_path,
        has_catalog=has_catalog,
        has_mockup=has_mockup,
    )


def default_board_id() -> str | None:
    """Pick a sensible default — the only board if there's exactly one."""
    boards = list_boards()
    if len(boards) == 1:
        return boards[0].id
    return None


# ────────────────────────── create / rename ──────────────────────────


def create_board(board_id: str, project_name: str | None = None) -> BoardInfo:
    """Create an empty board on disk and seed an example catalog skeleton."""
    if not is_valid_id(board_id):
        raise ValueError(
            f"Invalid board id {board_id!r}. Use lowercase letters, digits, "
            f"hyphens or underscores only."
        )
    root = config.BOARDS_DIR / board_id
    if root.exists():
        raise FileExistsError(f"Board {board_id!r} already exists at {root}")

    project_name = project_name or board_id
    root.mkdir(parents=True)
    (root / "mockup").mkdir()
    (root / "workspace").mkdir()
    (root / "board_assets").mkdir()

    # Seed an example catalog. Keeps the same structure as the existing
    # damnation board but blank designs / panels — the user fills it in.
    catalog_skeleton = {
        "project": project_name,
        "version": 1,
        "board_size": [1920, 1080],
        "style": {
            "reference_image": "mockup/board.png",
            "palette_size": 24,
            "prompt": "",
        },
        "board_spaces": {
            "layout": {},
            "designs": [],
        },
        "feature_panels": {"panels": []},
        "centerpiece": {
            "bbox": [780, 280, 1140, 800],
            "target_size": [360, 520],
            "prompt": "",
            "needs_active": False,
            "active_kind": "none",
        },
    }
    (root / "catalog.yml").write_text(yaml.safe_dump(catalog_skeleton, sort_keys=False))
    return _load_board_info(board_id)


def rename_board_project(board_id: str, new_project_name: str) -> BoardInfo:
    """Update the human-readable `project` field in catalog.yml. Does NOT
    rename the directory or the URL slug — that's a separate, riskier op."""
    info = get_board(board_id)
    if info is None:
        raise FileNotFoundError(f"Unknown board {board_id!r}")
    if not info.has_catalog:
        raise FileNotFoundError(f"Board {board_id!r} has no catalog.yml yet")
    new_name = (new_project_name or "").strip()
    if not new_name:
        raise ValueError("Project name cannot be empty")

    with info.catalog_path.open() as f:
        data = yaml.safe_load(f) or {}
    data["project"] = new_name
    info.catalog_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return _load_board_info(board_id)


# ────────────────────────── migration from flat layout ──────────────────────────


def migrate_legacy_flat_layout(target_board_id: str = "damnation") -> BoardInfo | None:
    """One-time migration: convert the original flat repo layout into a board.

    Old layout:  catalog/board.yml + workspace/ + mockup/ + board_assets/
    New layout:  boards/<id>/{catalog.yml, workspace/, mockup/, board_assets/}

    Idempotent: if the target board already exists OR there's no legacy data,
    this is a no-op. Returns the migrated board, or None if nothing migrated.
    """
    legacy_catalog = config.REPO_ROOT / "catalog" / "board.yml"
    if not legacy_catalog.exists():
        return None

    target_root = config.BOARDS_DIR / target_board_id
    if target_root.exists():
        return _load_board_info(target_board_id)

    config.BOARDS_DIR.mkdir(exist_ok=True)
    target_root.mkdir()

    # 1. Catalog: copy as catalog.yml (single canonical name inside the board).
    shutil.copy2(legacy_catalog, target_root / "catalog.yml")

    # 2. Workspace, mockup, board_assets: move (don't copy — these can be huge).
    for name in ("workspace", "mockup", "board_assets"):
        src = config.REPO_ROOT / name
        dst = target_root / name
        if src.exists():
            shutil.move(str(src), str(dst))
        else:
            dst.mkdir()

    # 3. Leave the old catalog/ dir behind as an "archive" so nothing in the
    #    user's working tree disappears unexpectedly. They can delete it.
    return _load_board_info(target_board_id)

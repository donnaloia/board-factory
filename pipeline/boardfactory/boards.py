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

    # Seed with the standard 1920×1080 board geometry. Every new board shares
    # the same cell layout (12 top, 12 bottom, 5 left, 5 right, 12 interior
    # panels around a central piece) — only the prompts are theme-specific.
    # The user renames/rewrites each prompt to match their theme.
    catalog_skeleton = {
        "project": project_name,
        "version": 1,
        "board_size": [1920, 1080],
        "style": {
            "reference_image": "mockup/board.png",
            "palette_size": 36,
            "prompt": "",
        },
        "generation": {
            "palette_size": 36,
            "provider": "openai",
            "openai": {"model": "gpt-image-2", "quality": "low"},
            "pixellab": {"model": "pixflux_sharp"},
            "configured": False,
        },
        "centerpiece": {
            "bbox": [700, 180, 1220, 900],
            "target_size": [520, 720],
            "prompt": "",
            "needs_active": False,
            "active_kind": "none",
        },
        "board_spaces": {
            "layout": {
                "top_row": {
                    "count": 12, "start": [0, 0], "axis": "x", "size": [160, 180],
                },
                "bottom_row": {
                    "count": 12, "start": [0, 900], "axis": "x", "size": [160, 180],
                },
                "left_col": {
                    "count": 5, "start": [0, 180], "axis": "y", "size": [180, 144],
                },
                "right_col": {
                    "count": 5, "start": [1740, 180], "axis": "y", "size": [180, 144],
                },
            },
            "designs": [
                # ── corners ──
                {"id": "corner_tl", "prompt": "", "positions": ["top_row.0"]},
                {"id": "corner_tr", "prompt": "", "positions": ["top_row.11"]},
                {"id": "corner_bl", "prompt": "", "positions": ["bottom_row.0"]},
                {"id": "corner_br", "prompt": "", "positions": ["bottom_row.11"]},
                # ── top row spaces ──
                {"id": "top_banner_a", "prompt": "", "positions": ["top_row.5"]},
                {"id": "top_banner_b", "prompt": "", "positions": ["top_row.7"]},
                {
                    "id": "top_space_a", "prompt": "",
                    "positions": ["top_row.1", "top_row.4", "top_row.8"],
                },
                {
                    "id": "top_space_b", "prompt": "",
                    "positions": ["top_row.2", "top_row.6", "top_row.9"],
                },
                {"id": "top_space_c", "prompt": "", "positions": ["top_row.3", "top_row.10"]},
                # ── bottom row spaces ──
                {"id": "bottom_banner_a", "prompt": "", "positions": ["bottom_row.5"]},
                {"id": "bottom_banner_b", "prompt": "", "positions": ["bottom_row.6"]},
                {
                    "id": "bottom_space_a", "prompt": "",
                    "positions": ["bottom_row.1", "bottom_row.4"],
                },
                {
                    "id": "bottom_space_b", "prompt": "",
                    "positions": ["bottom_row.2", "bottom_row.10"],
                },
                {
                    "id": "bottom_space_c", "prompt": "",
                    "positions": ["bottom_row.3", "bottom_row.8"],
                },
                {"id": "bottom_space_d", "prompt": "", "positions": ["bottom_row.9"]},
                {"id": "bottom_battle", "prompt": "", "positions": ["bottom_row.7"]},
                # ── side column spaces ──
                {
                    "id": "side_property", "prompt": "",
                    "positions": [
                        "left_col.0", "left_col.1", "left_col.3", "left_col.4",
                        "right_col.1", "right_col.2", "right_col.3",
                    ],
                },
                {
                    "id": "side_battle", "prompt": "",
                    "positions": ["left_col.2", "right_col.0", "right_col.4"],
                },
                # ── top row battle ──
                {"id": "top_battle", "prompt": "", "positions": ["top_row.3"]},
            ],
        },
        "feature_panels": {
            "panels": [
                # Left column of interior panels (3 rows × 1 col)
                {
                    "id": "panel_left_top",
                    "bbox": [180, 180, 440, 420], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_left_mid",
                    "bbox": [180, 420, 440, 660], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_left_bot",
                    "bbox": [180, 660, 440, 900], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                # Center-left interior panels
                {
                    "id": "panel_cleft_top",
                    "bbox": [440, 180, 700, 420], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_cleft_mid",
                    "bbox": [440, 420, 700, 660], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_cleft_bot",
                    "bbox": [440, 660, 700, 900], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                # Center-right interior panels
                {
                    "id": "panel_cright_top",
                    "bbox": [1220, 180, 1480, 420], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_cright_mid",
                    "bbox": [1220, 420, 1480, 660], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_cright_bot",
                    "bbox": [1220, 660, 1480, 900], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                # Right column of interior panels
                {
                    "id": "panel_right_top",
                    "bbox": [1480, 180, 1740, 420], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_right_mid",
                    "bbox": [1480, 420, 1740, 660], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
                {
                    "id": "panel_right_bot",
                    "bbox": [1480, 660, 1740, 900], "target_size": [260, 240],
                    "prompt": "", "needs_active": False,
                },
            ],
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

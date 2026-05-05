"""Multi-board registry — list, create boards on disk.

Each board is a self-contained directory under the configured per-board
data root (``data/boards/`` by default; see ``boardfactory.config`` and
the app's ``BoardStore``). The full catalog spec — including the human-
readable ``project`` title — lives in the application database
(see ``app.services.board_definition``); the pipeline consumes
``Catalog`` objects assembled from that DB layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BoardInfo:
    """On-disk view of a board.

    The ``project`` title is filled in by the *app* layer when it is needed
    for UI; pipeline tools usually only care about ``id`` and ``has_mockup``.
    """

    id: str                # slug, e.g. "damnation"
    project: str           # display name; pipeline-only callers may pass id
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


def is_board_uuid(board_id: str) -> bool:
    """True if ``board_id`` is a UUID string (folder names after migration 0015)."""
    return bool(_UUID_RE.match(board_id))


def _user_dir_name(s: str) -> bool:
    """Heuristic: app user ids are ``uuid.uuid4().hex`` (32 hex chars)."""
    return len(s) == 32 and all(c in "0123456789abcdef" for c in s.lower())


# ────────────────────────── default catalog (dict for DB persist) ──────────────────────────


def default_catalog_dict(board_id: str, project_name: str) -> dict[str, Any]:
    """Return the standard new-board catalog as a plain dict.

    ``board_id`` is accepted for API symmetry; the skeleton is shared across
    new boards. Persist with ``app.services.board_definition.persist_catalog_dict``.
    """
    _ = board_id
    return {
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
                {"id": "corner_tl", "prompt": "", "positions": ["top_row.0"]},
                {"id": "corner_tr", "prompt": "", "positions": ["top_row.11"]},
                {"id": "corner_bl", "prompt": "", "positions": ["bottom_row.0"]},
                {"id": "corner_br", "prompt": "", "positions": ["bottom_row.11"]},
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
                {"id": "top_battle", "prompt": "", "positions": ["top_row.3"]},
            ],
        },
        "feature_panels": {
            "panels": [
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


# ────────────────────────── list / read ──────────────────────────


def list_boards() -> list[BoardInfo]:
    """Return every board on disk, sorted alphabetically by id (canonical).

    Walks the canonical ``<boards>/<user_id>/<board_uuid>/`` layout only.
    Legacy flat ``<boards>/<slug>/`` directories and ``board_disk_map``
    aliases were removed once all checkouts had been reconciled (see
    ``app/scripts/reconcile_board_dirs.py``).
    """
    root_dir = config.BOARDS_DIR
    if not root_dir.exists():
        return []

    out: list[BoardInfo] = []
    for user_dir in sorted(root_dir.iterdir()):
        if not user_dir.is_dir() or not _user_dir_name(user_dir.name):
            continue
        for board_dir in sorted(user_dir.iterdir()):
            if not board_dir.is_dir():
                continue
            canonical = board_dir.name
            if not (is_board_uuid(canonical) or is_valid_id(canonical)):
                continue
            out.append(_load_board_info_at(canonical, board_dir))

    out.sort(key=lambda b: b.id)
    return out


def get_board(board_id: str) -> BoardInfo | None:
    if not (is_board_uuid(board_id) or is_valid_id(board_id)):
        return None
    try:
        root = config.board_root(board_id)
    except (RuntimeError, LookupError):
        # No active board, or the app's resolver raised BoardNotFound
        # because there's no ``owned_boards`` row.
        return None
    if not root.exists() or not root.is_dir():
        return None
    return _load_board_info_at(board_id, root)


def _load_board_info(board_id: str) -> BoardInfo:
    return _load_board_info_at(board_id, config.board_root(board_id))


def _load_board_info_at(canonical_id: str, root: Path) -> BoardInfo:
    """Synthesize a ``BoardInfo`` from on-disk state only.

    The catalog and project name now live in Postgres; the app layer fills
    in ``project`` post-hoc. Pipeline-only tools that don't reach into the
    DB get the id as the project name, which is sufficient for those use
    cases.
    """
    has_mockup = (root / "mockup").exists() and any((root / "mockup").iterdir())
    return BoardInfo(id=canonical_id, project=canonical_id, has_mockup=has_mockup)


def default_board_id() -> str | None:
    """Pick a sensible default — the only board if there's exactly one."""
    boards = list_boards()
    if len(boards) == 1:
        return boards[0].id
    return None


# ────────────────────────── create ──────────────────────────


def create_board(board_id: str, project_name: str | None = None) -> BoardInfo:
    """Create directory skeleton for a new board (mockup, workspace, exports).

    Does **not** touch the database — the web app persists the initial catalog
    with ``persist_catalog_dict`` after this returns.
    """
    if not (is_board_uuid(board_id) or is_valid_id(board_id)):
        raise ValueError(
            f"Invalid board id {board_id!r}. Use a UUID string or a slug "
            f"(lowercase letters, digits, hyphens or underscores)."
        )
    root = config.board_root(board_id)
    if root.exists():
        raise FileExistsError(f"Board {board_id!r} already exists at {root}")

    root.mkdir(parents=True)
    (root / "mockup").mkdir()
    (root / "workspace").mkdir()
    (root / "export").mkdir()

    return _load_board_info(board_id)

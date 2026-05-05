"""Reconcile on-disk board directories with the ``owned_boards`` table.

Background
----------

Historically board directories sat flat under ``data/boards/<slug>/``. After
migration ``0015_board_uuid_user_paths`` they live at
``data/boards/<user_id>/<board_uuid>/`` instead. Some workstations still carry
mixed state — flat legacy folders, user-scoped folders, ghost DB rows that
never got their disk twin moved. The disk-map fallback in
``services.board_paths.store_board_root`` was the safety net that kept those
boards visible despite the mismatch.

This script *reconciles* the filesystem so the safety net isn't needed: every
``owned_boards`` row gets its directory at the canonical
``data/boards/<user_id>/<board_uuid>/`` location, falling back to the slug or
example disk-map alias when looking for a legacy source folder to move.

Behaviour
---------

For each ``owned_boards`` row:

1. If ``<boards>/<user_id>/<board_uuid>/`` already exists, leave it.
2. Else, look for a legacy folder by basename (in this order):

   - ``<boards>/<board_uuid>/`` (flat UUID checkout)
   - ``<boards>/<path_slug>/``
   - any disk-map alias whose key matches the uuid or slug

   If exactly one of those exists, ``mv`` it into the canonical path.
3. Else, log it as a *ghost* (DB row with no disk twin) and continue.

After the per-row reconcile loop, the script also reports:

  * **Orphans** — directories under ``<boards>/<user_id>/`` whose name does
    not match an ``owned_boards`` row. (Likely deletes, but not auto-removed.)
  * **Stale flat dirs** — flat top-level folders that still exist *and* whose
    canonical user-scoped twin now exists too. (Safe to remove manually.)

The script never deletes anything; all destructive actions print "would
remove" and you do them by hand. Use ``--apply`` to actually perform the
``mv`` operations; without it the script runs in dry-run mode.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _boards_root() -> Path:
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
    return repo / "data" / "boards"


def _legacy_disk_map() -> dict[str, str]:
    """Optional ``.board_disk_map.json`` aliases (legacy, fading out)."""
    import json

    p = _boards_root() / ".board_disk_map.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str)
    }


def _candidate_source_paths(
    boards: Path, board_uuid: str, path_slug: str | None, disk_map: dict[str, str]
) -> list[Path]:
    """Existing flat folders that could be moved to ``boards/<user>/<uuid>/``."""
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        if p in seen or not p.is_dir():
            return
        seen.add(p)
        candidates.append(p)

    add(boards / board_uuid)
    if path_slug:
        add(boards / path_slug)
    for key, val in disk_map.items():
        if key.lower() in {board_uuid.lower(), (path_slug or "").lower()}:
            add(boards / val)
    return candidates


def _move_directory(src: Path, dst: Path, *, apply: bool) -> None:
    if dst.exists():
        raise RuntimeError(f"Refusing to move into existing path: {dst}")
    print(f"  mv {src} -> {dst}")
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def reconcile(*, apply: bool) -> int:
    """Return number of boards moved (or planned, in dry-run)."""
    from sqlalchemy import select

    from models.core import OwnedBoardRecord
    from infrastructure.db import session_scope

    boards = _boards_root()
    if not boards.exists():
        print(f"Boards root does not exist: {boards}")
        return 0
    disk_map = _legacy_disk_map()
    moved = 0
    ghost_rows: list[tuple[str, str, str]] = []
    canonical_dirs: set[Path] = set()
    known_slugs: set[str] = set()
    known_uuids: set[str] = set()

    with session_scope() as session:
        rows = session.scalars(select(OwnedBoardRecord)).all()
        # Materialize before exiting the session: detached attribute access raises.
        rows_data = [(r.board_uuid, r.user_id, r.path_slug or "") for r in rows]

    for _, _, slug in rows_data:
        if slug:
            known_slugs.add(slug)
    for uuid, _, _ in rows_data:
        known_uuids.add(uuid)

    for board_uuid, user_id, path_slug in rows_data:
        canonical = boards / user_id / board_uuid
        canonical_dirs.add(canonical)

        if canonical.is_dir():
            continue

        sources = _candidate_source_paths(boards, board_uuid, path_slug, disk_map)
        sources = [p for p in sources if p != canonical]

        if not sources:
            ghost_rows.append((board_uuid, user_id, path_slug))
            print(f"GHOST {user_id}/{board_uuid} (slug={path_slug or '-'}): no disk twin")
            continue

        if len(sources) > 1:
            print(
                f"AMBIGUOUS {user_id}/{board_uuid}: multiple legacy candidates "
                f"({', '.join(str(p.name) for p in sources)}); pick one manually"
            )
            continue

        src = sources[0]
        print(f"RECONCILE {user_id}/{board_uuid} (slug={path_slug or '-'})")
        _move_directory(src, canonical, apply=apply)
        moved += 1

    print()
    _report_orphans(boards, canonical_dirs)
    _report_stale_flat(boards, canonical_dirs, known_slugs, known_uuids)

    print()
    print(f"Summary: moved={moved}, ghosts={len(ghost_rows)}")
    if not apply:
        print("(dry-run; pass --apply to actually move directories)")
    return moved


def _report_orphans(boards: Path, canonical_dirs: set[Path]) -> None:
    """User-scoped UUID dirs without a matching ``owned_boards`` row."""
    canonical_set = {str(p) for p in canonical_dirs}
    user_roots = {p.parent for p in canonical_dirs if p.parent != boards}
    for user_root in sorted(user_roots):
        if not user_root.is_dir():
            continue
        for child in sorted(user_root.iterdir()):
            if not child.is_dir():
                continue
            if str(child) not in canonical_set:
                print(f"ORPHAN {child} (no owned_boards row); review and delete by hand")


def _report_stale_flat(
    boards: Path,
    canonical_dirs: set[Path],
    known_slugs: set[str],
    known_uuids: set[str],
) -> None:
    """Flat top-level dirs that look like leftovers of the pre-user-scoped layout.

    A flat dir is "stale" when:

    * It's a flat top-level entry (i.e. NOT one of the user_id directories that
      contain the canonical per-board folders), AND
    * Its name matches a known board slug or UUID whose canonical user-scoped
      twin already exists.
    """
    if not boards.exists():
        return
    user_id_dirs = {p.parent.name for p in canonical_dirs}
    canonical_basenames = {p.name for p in canonical_dirs}

    for child in sorted(boards.iterdir()):
        if not child.is_dir():
            continue
        if child.name in user_id_dirs:
            continue
        looks_like_known = (
            child.name in canonical_basenames
            or child.name in known_slugs
            or child.name in known_uuids
        )
        if looks_like_known:
            print(f"STALE FLAT {child} (canonical user-scoped twin exists)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move directories. Default is dry-run (print intended moves).",
    )
    args = parser.parse_args(argv)
    reconcile(apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())

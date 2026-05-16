"""Move per-token workspace dirs from the old board-nested layout to the new
top-level layout::

    data/boards/<linked_board_id>/workspace/tokens/<slug>/
                            \\----- (old) -----/

    data/tokens/<token_id>/
              \\--- (new) ---/

Runs after the Alembic ``0008_tokens_decouple_from_boards`` migration has
applied: at that point ``token_records`` has ``linked_board_id`` + ``slug`` +
``id`` columns. This script reads those rows via SQLAlchemy core (no ORM models
needed — keeps the script working even if the app code is mid-rollout) and
moves the directories with ``shutil.move``.

Idempotent: if the new path already exists, the row is skipped; if the old
path is gone (already moved or never existed), the row is reported and
skipped. Unlinked tokens (``linked_board_id IS NULL``) are skipped because
their old path can't be reconstructed.

Invoke via ``make migrate-tokens``.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from infrastructure.db import session_scope


_DEFAULT_TOKENS_SUBDIR = "tokens"
_DEFAULT_BOARDS_SUBDIR = "boards"


def _repo_root() -> Path:
    return Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def _boards_dir() -> Path:
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return _repo_root() / "data" / _DEFAULT_BOARDS_SUBDIR


def _tokens_dir() -> Path:
    explicit = os.environ.get("BOARDFACTORY_TOKENS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return _repo_root() / "data" / _DEFAULT_TOKENS_SUBDIR


@dataclass
class MoveResult:
    token_id: str
    slug: str
    linked_board_id: str | None
    old_path: Path | None
    new_path: Path
    action: str  # "moved" | "skipped_new_exists" | "skipped_old_missing" | "skipped_unlinked"


def _fetch_tokens() -> list[tuple[str, str, str | None]]:
    """Return list of (id, slug, linked_board_id) for every token.

    PostgreSQL / drivers often return ``UUID`` objects for uuid columns;
    normalize to ``str`` so ``pathlib.Path`` joins work reliably.
    """
    with session_scope() as session:
        rows = session.execute(
            sa.text("SELECT id, slug, linked_board_id FROM token_records")
        ).all()
    out: list[tuple[str, str, str | None]] = []
    for r in rows:
        tid = str(r[0])
        slug = str(r[1])
        lid = None if r[2] is None else str(r[2])
        out.append((tid, slug, lid))
    return out


def migrate(
    dry_run: bool = False,
    *,
    tokens: list[tuple[str, str, str | None]] | None = None,
    boards_root: Path | None = None,
    tokens_root: Path | None = None,
) -> list[MoveResult]:
    """Move per-token workspaces. ``tokens`` / roots are injectable for tests.

    Default behavior (no injection):
      - Pull every row via ``_fetch_tokens()``
      - Use the env-resolved ``data/boards`` / ``data/tokens`` roots
    """
    if boards_root is None:
        boards_root = _boards_dir()
    if tokens_root is None:
        tokens_root = _tokens_dir()
    tokens_root.mkdir(parents=True, exist_ok=True)
    token_iter = tokens if tokens is not None else _fetch_tokens()

    results: list[MoveResult] = []
    for raw_tid, raw_slug, raw_lid in token_iter:
        token_id = str(raw_tid)
        slug = str(raw_slug)
        linked_board_id = None if raw_lid is None else str(raw_lid)

        new_path = tokens_root / token_id

        if linked_board_id is None:
            results.append(
                MoveResult(
                    token_id=token_id,
                    slug=slug,
                    linked_board_id=None,
                    old_path=None,
                    new_path=new_path,
                    action="skipped_unlinked",
                )
            )
            continue

        old_path = boards_root / linked_board_id / "workspace" / "tokens" / slug

        if new_path.exists():
            results.append(
                MoveResult(
                    token_id=token_id,
                    slug=slug,
                    linked_board_id=linked_board_id,
                    old_path=old_path,
                    new_path=new_path,
                    action="skipped_new_exists",
                )
            )
            continue

        if not old_path.exists():
            results.append(
                MoveResult(
                    token_id=token_id,
                    slug=slug,
                    linked_board_id=linked_board_id,
                    old_path=old_path,
                    new_path=new_path,
                    action="skipped_old_missing",
                )
            )
            continue

        if not dry_run:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
        results.append(
            MoveResult(
                token_id=token_id,
                slug=slug,
                linked_board_id=linked_board_id,
                old_path=old_path,
                new_path=new_path,
                action="moved",
            )
        )

    return results


def _print_report(results: list[MoveResult]) -> None:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.action] = counts.get(r.action, 0) + 1
        print(
            f"  [{r.action}] {r.token_id} ({r.slug})"
            + (f"  from {r.old_path}" if r.old_path else "")
            + f"  → {r.new_path}"
        )
    print()
    print("Summary:")
    for action, n in sorted(counts.items()):
        print(f"  {action}: {n}")
    print(f"  total: {len(results)}")


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    print(
        "Migrating token workspaces to top-level layout"
        + (" [dry-run]" if dry_run else "")
    )
    print(f"  boards root: {_boards_dir()}")
    print(f"  tokens root: {_tokens_dir()}")
    print()
    results = migrate(dry_run=dry_run)
    _print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

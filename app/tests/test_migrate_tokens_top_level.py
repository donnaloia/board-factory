"""Tests for ``scripts/migrate_tokens_top_level``.

Uses injectable token data + temp dirs so the script can be exercised without
touching the real database or real ``data/boards`` layout.
"""

from __future__ import annotations

from pathlib import Path

from scripts.migrate_tokens_top_level import migrate


def _seed_old_token(
    boards_root: Path, *, board_id: str, slug: str, payload: bytes = b"hello"
) -> Path:
    """Lay out one token under the legacy ``data/boards/...`` layout."""
    old = boards_root / board_id / "workspace" / "tokens" / slug
    old.mkdir(parents=True, exist_ok=True)
    (old / "design_lock.json").write_bytes(payload)
    (old / "references").mkdir(exist_ok=True)
    (old / "references" / "canonical.png").write_bytes(b"\x89PNG")
    return old


def test_migrate_moves_each_token(tmp_path: Path):
    boards_root = tmp_path / "boards"
    tokens_root = tmp_path / "tokens"
    _seed_old_token(boards_root, board_id="board-A", slug="pawn-1")
    _seed_old_token(boards_root, board_id="board-A", slug="knight-2")
    _seed_old_token(boards_root, board_id="board-B", slug="dragon-1")

    results = migrate(
        dry_run=False,
        tokens=[
            ("tok-001", "pawn-1", "board-A"),
            ("tok-002", "knight-2", "board-A"),
            ("tok-003", "dragon-1", "board-B"),
        ],
        boards_root=boards_root,
        tokens_root=tokens_root,
    )

    assert sorted(r.action for r in results) == ["moved", "moved", "moved"]
    assert (tokens_root / "tok-001" / "design_lock.json").exists()
    assert (tokens_root / "tok-002" / "references" / "canonical.png").exists()
    assert (tokens_root / "tok-003" / "design_lock.json").exists()
    # Old paths should be gone after a successful move.
    assert not (boards_root / "board-A" / "workspace" / "tokens" / "pawn-1").exists()


def test_migrate_is_idempotent(tmp_path: Path):
    boards_root = tmp_path / "boards"
    tokens_root = tmp_path / "tokens"
    _seed_old_token(boards_root, board_id="board-A", slug="pawn-1")

    tokens = [("tok-001", "pawn-1", "board-A")]
    first = migrate(
        dry_run=False,
        tokens=tokens,
        boards_root=boards_root,
        tokens_root=tokens_root,
    )
    second = migrate(
        dry_run=False,
        tokens=tokens,
        boards_root=boards_root,
        tokens_root=tokens_root,
    )
    assert [r.action for r in first] == ["moved"]
    assert [r.action for r in second] == ["skipped_new_exists"]


def test_migrate_skips_unlinked_tokens(tmp_path: Path):
    boards_root = tmp_path / "boards"
    tokens_root = tmp_path / "tokens"

    results = migrate(
        dry_run=False,
        tokens=[("tok-unlinked", "free", None)],
        boards_root=boards_root,
        tokens_root=tokens_root,
    )
    assert [r.action for r in results] == ["skipped_unlinked"]
    assert not (tokens_root / "tok-unlinked").exists()


def test_migrate_skips_when_old_path_missing(tmp_path: Path):
    boards_root = tmp_path / "boards"
    tokens_root = tmp_path / "tokens"
    # Don't seed anything on disk.
    results = migrate(
        dry_run=False,
        tokens=[("tok-001", "pawn-1", "board-A")],
        boards_root=boards_root,
        tokens_root=tokens_root,
    )
    assert [r.action for r in results] == ["skipped_old_missing"]


def test_migrate_dry_run_does_not_move(tmp_path: Path):
    boards_root = tmp_path / "boards"
    tokens_root = tmp_path / "tokens"
    _seed_old_token(boards_root, board_id="board-A", slug="pawn-1")

    results = migrate(
        dry_run=True,
        tokens=[("tok-001", "pawn-1", "board-A")],
        boards_root=boards_root,
        tokens_root=tokens_root,
    )
    assert [r.action for r in results] == ["moved"]
    # The old path should still exist; nothing was actually moved.
    assert (
        boards_root / "board-A" / "workspace" / "tokens" / "pawn-1"
    ).exists()
    assert not (tokens_root / "tok-001").exists()

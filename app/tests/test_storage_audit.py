"""Coverage for ``infrastructure.storage_audit``.

Read-only audit: walks the boards/decks/tokens roots and bucketises every
file. These tests construct deliberately-broken on-disk states (orphan
file, dangling pointer, unknown bucket, transient bucket) and assert the
report flags each one correctly.
"""

from __future__ import annotations

import uuid
from pathlib import Path


def _boards_root() -> Path:
    from infrastructure.storage_audit import _boards_root  # type: ignore[attr-defined]

    return _boards_root()


def _decks_root() -> Path:
    from infrastructure.storage_audit import _decks_root  # type: ignore[attr-defined]

    return _decks_root()


def _tokens_root() -> Path:
    from infrastructure.storage_audit import _tokens_root  # type: ignore[attr-defined]

    return _tokens_root()


def _write(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_to_board(board_id: str, rel: str, payload: bytes = b"x") -> None:
    """Write a file under the per-board root via the configured store.

    Boards live at ``<boards_root>/<user_id>/<board_id>/...`` — going through
    the store keeps the test honest about that layout.
    """
    from infrastructure import board_store as bs

    bs.get_store().write_bytes(board_id, rel, payload)


# ────────────────────────── happy paths ──────────────────────────


def test_run_audit_against_clean_repo_yields_empty_report(isolated_repo):
    from infrastructure.storage_audit import run_audit

    report = run_audit()
    assert report.files == []
    assert report.dangling == []


def test_seeded_board_with_only_mockup_classifies_as_tracked_referenced(seeded_board):
    """The conftest fixture seeds ``mockup/board.png`` for an owned board."""
    from infrastructure.storage_audit import run_audit

    report = run_audit()
    mockup = [f for f in report.files if f.bucket == "board.mockup"]
    assert len(mockup) == 1
    assert mockup[0].rel_path.endswith("/mockup/board.png")
    assert mockup[0].lifecycle == "tracked"
    assert mockup[0].referenced is True


# ────────────────────────── orphans ──────────────────────────


def test_board_root_with_no_db_row_is_orphan(isolated_repo):
    """A directory under ``data/boards/`` with no matching ``owned_boards`` row
    must be flagged as ``board.orphan_root`` and lifecycle=tracked, ref=False.
    """
    from infrastructure.storage_audit import run_audit

    stale_id = str(uuid.uuid4())
    _write(_boards_root() / stale_id / "mockup" / "board.png")

    report = run_audit()
    orphan = [f for f in report.files if f.bucket == "board.orphan_root"]
    assert len(orphan) == 1
    assert orphan[0].lifecycle == "tracked"
    assert orphan[0].referenced is False


def test_history_png_with_no_asset_versions_row_is_orphan(seeded_board):
    """A history file written without a corresponding ``asset_versions`` row
    must show as a tracked-but-unreferenced (orphan) file.
    """
    from infrastructure.storage_audit import run_audit

    _write_to_board(
        seeded_board.id,
        "workspace/history/spaces/ghost_cell/1700000000000_v.png",
    )

    report = run_audit()
    history = [
        f for f in report.files if f.bucket == "board.workspace.history.spaces"
    ]
    assert len(history) == 1
    assert history[0].lifecycle == "tracked"
    assert history[0].referenced is False


def test_card_history_classified_as_orphan(isolated_repo, test_user):
    """Cards have no history concept — any file under ``cards/<idx>/history/``
    is from a previous regen contract and must show up as a tracked-orphan
    so ``make audit-storage ARGS='--apply'`` can clean it up.
    """
    import time

    from domains.cards import repository as cards_repo
    from infrastructure.storage_audit import run_audit

    deck = cards_repo.create_deck(
        owner_user_id=test_user.id, path_slug="t", project_name="t"
    )
    _write(
        _decks_root()
        / deck.id
        / "cards"
        / "0"
        / "history"
        / f"{int(time.time() * 1000)}_card.png"
    )

    report = run_audit()
    history = [f for f in report.files if f.bucket == "deck.cards.history"]
    assert len(history) == 1
    assert history[0].lifecycle == "tracked"
    assert history[0].referenced is False


# ────────────────────────── dangling ──────────────────────────


def test_dangling_pointer_when_asset_versions_row_missing_file(seeded_board):
    """``asset_versions`` row whose ``rel_path`` does not exist on disk must
    show up in ``report.dangling`` with the right table/column.
    """
    from sqlalchemy import insert

    from domains.spaces.assets.models import AssetVersionRecord
    from domains.spaces.models import CellRecord
    from infrastructure.db import session_scope
    from infrastructure.storage_audit import run_audit

    with session_scope() as s:
        cell = CellRecord(
            board_uuid=seeded_board.id,
            kind="perimeter",
            slug="ghost",
            position_index=0,
            space_kind="standard",
            positions_json=[[0, 0]],
        )
        s.add(cell)
        s.flush()
        s.execute(
            insert(AssetVersionRecord).values(
                board_uuid=seeded_board.id,
                cell_id=cell.id,
                category="spaces",
                asset_id="ghost",
                basename="missing.png",
                rel_path="workspace/history/spaces/ghost/missing.png",
                ts_ms=1,
            )
        )

    report = run_audit()
    dangling = [
        d
        for d in report.dangling
        if d.table == "asset_versions"
        and d.expected_rel.endswith("missing.png")
    ]
    assert len(dangling) == 1
    assert dangling[0].column == "rel_path"


# ────────────────────────── transient buckets ──────────────────────────


def test_frame_proposals_classified_as_transient(seeded_board):
    """``workspace/frames/_proposals/...`` files are intermediates with no
    DB pointer — must come back as ``transient`` with ``referenced=None``.
    """
    from infrastructure.storage_audit import run_audit

    _write_to_board(
        seeded_board.id,
        "workspace/frames/_proposals/abcdef123456/candidate_0.png",
    )

    report = run_audit()
    proposals = [
        f for f in report.files if f.bucket == "board.workspace.frames.proposals"
    ]
    assert len(proposals) == 1
    assert proposals[0].lifecycle == "transient"
    assert proposals[0].referenced is None


def test_animation_proposals_classified_as_transient(seeded_board):
    from infrastructure.storage_audit import run_audit

    cell_id = str(uuid.uuid4())
    _write_to_board(
        seeded_board.id,
        f"workspace/animations/{cell_id}/_proposals/deadbeef0001/0.gif",
    )

    report = run_audit()
    proposals = [
        f for f in report.files if f.bucket == "board.workspace.animations.proposals"
    ]
    assert len(proposals) == 1
    assert proposals[0].lifecycle == "transient"


# ────────────────────────── render ──────────────────────────


def test_render_text_contains_section_headers(isolated_repo):
    from infrastructure.storage_audit import render_text, run_audit

    out = render_text(run_audit())
    assert "Storage audit" in out
    assert "Boards root:" in out


# ────────────────────────── prune orphans ──────────────────────────


def test_prune_orphan_files_dry_run_does_not_delete(seeded_board):
    from infrastructure import board_store as bs
    from infrastructure.storage_audit import prune_orphan_files, run_audit

    rel = "workspace/history/spaces/ghost_cell/1700000000000_v.png"
    _write_to_board(seeded_board.id, rel)
    assert bs.get_store().exists(seeded_board.id, rel)

    report = run_audit()
    prune = prune_orphan_files(report, apply=False)
    assert prune.deleted_files >= 1
    assert prune.dry_run is True
    assert bs.get_store().exists(seeded_board.id, rel)


def test_prune_orphan_files_apply_deletes_orphans(seeded_board):
    from infrastructure.storage_audit import prune_orphan_files, run_audit
    from infrastructure import board_store as bs

    rel = "workspace/history/spaces/ghost_prune/1700000000001_v.png"
    bs.get_store().write_bytes(seeded_board.id, rel, b"x")

    report = run_audit()
    orphans_before = report.orphan_files()
    assert any("ghost_prune" in f.rel_path for f in orphans_before)

    prune = prune_orphan_files(report, apply=True)
    assert prune.deleted_files >= 1
    assert prune.dry_run is False
    assert not bs.get_store().exists(seeded_board.id, rel)


def test_prune_stale_workspace_removes_proposals(seeded_board):
    from infrastructure.storage_audit import prune_stale_workspace, run_audit

    rel = "workspace/frames/_proposals/abcdef123456/candidate_0.png"
    _write_to_board(seeded_board.id, rel)
    report = run_audit()
    assert any(f.bucket == "board.workspace.frames.proposals" for f in report.files)

    prune = prune_stale_workspace(report, apply=True)
    assert prune.deleted_files >= 1
    from infrastructure import board_store as bs

    assert not bs.get_store().exists(seeded_board.id, rel)


def test_prune_orphan_files_does_not_delete_transient(seeded_board):
    from infrastructure.storage_audit import prune_orphan_files, run_audit

    _write_to_board(
        seeded_board.id,
        "workspace/frames/_proposals/abcdef123456/candidate_0.png",
    )
    report = run_audit()
    proposals = [
        f for f in report.files if f.bucket == "board.workspace.frames.proposals"
    ]
    assert len(proposals) == 1

    assert all(
        f.bucket != "board.workspace.frames.proposals" for f in report.orphan_files()
    )
    prune = prune_orphan_files(report, apply=True)
    # File must still exist — transient, not an orphan under our definition
    from infrastructure import board_store as bs

    assert bs.get_store().exists(
        seeded_board.id,
        "workspace/frames/_proposals/abcdef123456/candidate_0.png",
    )


def test_prune_orphan_files_removes_card_history_orphans(isolated_repo, test_user):
    import time

    from domains.cards import repository as cards_repo
    from infrastructure.storage_audit import prune_orphan_files, run_audit

    deck = cards_repo.create_deck(
        owner_user_id=test_user.id, path_slug="prune-t", project_name="t"
    )
    history_file = (
        _decks_root()
        / deck.id
        / "cards"
        / "0"
        / "history"
        / f"{int(time.time() * 1000)}_card.png"
    )
    _write(history_file)

    report = run_audit()
    assert any(f.bucket == "deck.cards.history" for f in report.orphan_files())

    prune = prune_orphan_files(report, apply=True)
    assert prune.deleted_files >= 1
    assert not history_file.exists()

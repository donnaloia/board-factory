"""Service-layer tests for boards lifecycle.

Phase 1b coverage: list / get / create / rename / mockup_present.
"""

from __future__ import annotations

import uuid

import pytest


def test_get_board_unknown_raises(isolated_repo, test_user):
    from domains.boards import services as svc_boards

    missing = str(uuid.uuid4())
    with pytest.raises(svc_boards.BoardNotFound):
        svc_boards.get_board(test_user.id, missing)


def test_get_board_invalid_id(isolated_repo, test_user):
    from domains.boards import services as svc_boards

    with pytest.raises(svc_boards.InvalidBoardId):
        svc_boards.get_board(test_user.id, "Bad Id With Spaces")


def test_list_boards_returns_seeded(seeded_board, test_user):
    from domains.boards import services as svc_boards

    rows = svc_boards.list_boards(test_user.id)
    ids = {r.id for r in rows}
    assert seeded_board.id in ids
    row = next(r for r in rows if r.id == seeded_board.id)
    assert row.has_board_preview is False
    assert row.board_preview_asset_rest is None
    assert row.mockup_thumb_name == "board.png"


def test_list_boards_prefers_preview_thumb_when_present(seeded_board, test_user):
    from domains.boards import services as svc_boards
    from infrastructure import board_store as bs

    store = bs.get_store()
    store.write_bytes(
        seeded_board.id,
        "workspace/preview/board_idle.png",
        b"\x89PNG\r\n\x1a\n",
    )
    rows = svc_boards.list_boards(test_user.id)
    row = next(r for r in rows if r.id == seeded_board.id)
    assert row.has_board_preview is True
    assert row.board_preview_asset_rest == "preview/board_idle.png"
    assert row.mockup_thumb_name == "board.png"


def test_list_boards_includes_owned_board_without_disk_dir(isolated_repo, test_user):
    """Ownership + ``board_games`` row can exist without an on-disk tree yet."""
    import uuid as uuid_mod

    from boardfactory import boards as bf_boards
    from domains.boards import services as bd
    from domains.boards import repository as bo
    from domains.boards import services as svc_boards

    bid = str(uuid_mod.uuid4())
    bd.persist_catalog_dict(bid, bf_boards.default_catalog_dict(bid, "Demo Project"))
    bo.link_board_to_user(bid, test_user.id, path_slug="demo-board")

    rows = svc_boards.list_boards(test_user.id)
    assert len(rows) == 1
    assert rows[0].id == bid
    assert rows[0].path_slug == "demo-board"
    assert rows[0].project == "Demo Project"
    assert rows[0].has_catalog is True


def test_store_board_root_raises_for_unknown_uuid(isolated_repo):
    """``store_board_root`` no longer silently returns a path for unknown boards."""
    from domains.boards import repository as bp

    with pytest.raises(bp.BoardNotFound):
        bp.store_board_root("00000000-0000-0000-0000-000000000000")


def test_list_boards_most_recent_activity_first(isolated_repo, test_user):
    """Board picker sorts by latest ``board_games`` activity (catalog or palette)."""
    from domains.boards.models import BoardGameRecord
    from infrastructure.db import session_scope
    from domains.boards import services as svc_boards

    older = svc_boards.create_board(
        "aaa-board", owner_user_id=test_user.id, project_name="Older",
    )
    newer = svc_boards.create_board(
        "zzz-board", owner_user_id=test_user.id, project_name="Newer",
    )
    with session_scope() as session:
        session.get(BoardGameRecord, older.id).updated_ms = 100
        session.get(BoardGameRecord, newer.id).updated_ms = 500

    order = [r.id for r in svc_boards.list_boards(test_user.id)]
    assert order[0] == newer.id


def test_create_board_rejects_empty_owner(isolated_repo):
    from domains.boards import services as svc_boards

    with pytest.raises(ValueError, match="owner_user_id"):
        svc_boards.create_board("empty-owner-board", owner_user_id="")


def test_link_board_rejects_empty_user(isolated_repo):
    from domains.boards import repository as bo

    with pytest.raises(ValueError, match="user_id"):
        bo.link_board_to_user(str(uuid.uuid4()), "")


def test_create_board_then_collide(isolated_repo, test_user):
    from domains.boards import services as svc_boards

    summary = svc_boards.create_board(
        "brand-new", owner_user_id=test_user.id, project_name="Brand New",
    )
    assert summary.path_slug == "brand-new"
    assert len(summary.id) == 36
    assert summary.project == "Brand New"
    assert summary.has_catalog is True

    with pytest.raises(svc_boards.BoardExists):
        svc_boards.create_board("brand-new", owner_user_id=test_user.id)


def test_rename_board(seeded_board, test_user):
    from domains.boards import services as svc_boards

    summary = svc_boards.rename_board(test_user.id, seeded_board.id, "Renamed")
    assert summary.project == "Renamed"


def test_delete_board_removes_disk_and_db(seeded_board, test_user, isolated_repo):
    from domains.boards import services as bd
    from domains.boards import repository as bo
    from domains.boards import services as svc_boards
    from infrastructure import board_store as bs

    bid = seeded_board.id
    store = bs.get_store()
    assert store.board_exists(bid)
    svc_boards.delete_board(test_user.id, bid)
    assert not store.board_exists(bid)
    assert bd.load_catalog_dict(bid) is None
    assert not bo.user_owns_board(test_user.id, bid)
    with pytest.raises(svc_boards.BoardNotFound):
        svc_boards.get_board(test_user.id, bid)


def test_mockup_present_reports_default_path(seeded_board):
    from domains.boards import services as svc_boards

    exists, rel = svc_boards.mockup_present(seeded_board.id)
    assert exists is True
    assert rel == "mockup/board.png"


def test_clone_board_copies_disk_cells_and_asset_rows(seeded_board, test_user):
    from sqlalchemy import func, select

    from assets.models import AssetVersionRecord
    from domains.boards import services as svc_boards
    from domains.cells.models import CellRecord
    from infrastructure.db import session_scope

    with session_scope() as session:
        n_cells_src = session.scalar(
            select(func.count()).select_from(CellRecord).where(
                CellRecord.board_uuid == seeded_board.id
            )
        )
        n_av_src = session.scalar(
            select(func.count()).select_from(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == seeded_board.id
            )
        )

    clone = svc_boards.clone_board(test_user.id, seeded_board.id)

    assert clone.id != seeded_board.id
    assert clone.project == "Test Board (copy)"

    with session_scope() as session:
        n_cells_dst = session.scalar(
            select(func.count()).select_from(CellRecord).where(
                CellRecord.board_uuid == clone.id
            )
        )
        n_av_dst = session.scalar(
            select(func.count()).select_from(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == clone.id
            )
        )
    assert n_cells_dst == n_cells_src
    assert n_av_dst == n_av_src

    from infrastructure import board_store as bs

    assert bs.get_store().exists(clone.id, "mockup/board.png")


def test_clone_board_custom_slug(seeded_board, test_user):
    from domains.boards import services as svc_boards

    clone = svc_boards.clone_board(
        test_user.id, seeded_board.id, path_slug="my-clone",
    )
    assert clone.path_slug == "my-clone"


def test_clone_board_rejects_duplicate_slug(seeded_board, test_user):
    from domains.boards import services as svc_boards

    svc_boards.clone_board(test_user.id, seeded_board.id, path_slug="once-only")
    with pytest.raises(svc_boards.BoardExists):
        svc_boards.clone_board(test_user.id, seeded_board.id, path_slug="once-only")

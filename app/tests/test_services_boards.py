"""Service-layer tests for boards lifecycle.

Phase 1b coverage: list / get / create / rename / mockup_present.
"""

from __future__ import annotations

import pytest


def test_get_board_unknown_raises(isolated_repo, test_user):
    from services import boards as svc_boards

    with pytest.raises(svc_boards.BoardNotFound):
        svc_boards.get_board(test_user.id, "nope")


def test_get_board_invalid_id(isolated_repo, test_user):
    from services import boards as svc_boards

    with pytest.raises(svc_boards.InvalidBoardId):
        svc_boards.get_board(test_user.id, "Bad Id With Spaces")


def test_list_boards_returns_seeded(seeded_board, test_user):
    from services import boards as svc_boards

    rows = svc_boards.list_boards(test_user.id)
    ids = {r.id for r in rows}
    assert seeded_board.id in ids


def test_create_board_rejects_empty_owner(isolated_repo):
    from services import boards as svc_boards

    with pytest.raises(ValueError, match="owner_user_id"):
        svc_boards.create_board("empty-owner-board", owner_user_id="")


def test_link_board_rejects_empty_user(isolated_repo):
    from services import board_ownership as bo

    with pytest.raises(ValueError, match="user_id"):
        bo.link_board_to_user("any-board", "")


def test_create_board_then_collide(isolated_repo, test_user):
    from services import boards as svc_boards

    summary = svc_boards.create_board(
        "brand-new", owner_user_id=test_user.id, project_name="Brand New",
    )
    assert summary.id == "brand-new"
    assert summary.project == "Brand New"
    assert summary.has_catalog is True

    with pytest.raises(svc_boards.BoardExists):
        svc_boards.create_board("brand-new", owner_user_id=test_user.id)


def test_rename_board(seeded_board, test_user):
    from services import boards as svc_boards

    summary = svc_boards.rename_board(test_user.id, seeded_board.id, "Renamed")
    assert summary.project == "Renamed"


def test_delete_board_removes_disk_and_db(seeded_board, test_user, isolated_repo):
    from services import board_definition as bd
    from services import board_ownership as bo
    from services import boards as svc_boards
    from storage import board_store as bs

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
    from services import boards as svc_boards

    exists, rel = svc_boards.mockup_present(seeded_board.id)
    assert exists is True
    assert rel == "mockup/board.png"

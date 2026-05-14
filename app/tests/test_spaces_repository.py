"""Cells repository — direct DB I/O against the ``cells`` table."""

from __future__ import annotations

import pytest

from infrastructure.db import session_scope
from domains.spaces.models import CellRecord


def test_seeded_board_creates_one_cell_per_design_and_panel(isolated_repo, seeded_board, board_id):
    from domains.spaces import repository as spaces_repo

    cells = spaces_repo.list_for_board(board_id)
    kinds = {c.kind for c in cells}
    assert kinds == {"perimeter", "functional", "centerpiece"}

    spaces = [c for c in cells if c.kind == "perimeter"]
    assert len(spaces) == 19  # default catalog seeds 19 board space designs.
    panels = [c for c in cells if c.kind == "functional"]
    assert len(panels) == 12  # 12 feature panels in the default layout.
    centerpieces = [c for c in cells if c.kind == "centerpiece"]
    assert len(centerpieces) == 1


def test_find_id_resolves_category_to_kind(isolated_repo, seeded_board, board_id):
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(board_id, "spaces", "corner_tl")
    assert cell_id is not None

    assert spaces_repo.find_id(board_id, "panels", "panel_left_top") is not None
    assert spaces_repo.find_id(board_id, "centerpiece", "centerpiece") is not None
    assert spaces_repo.find_id(board_id, "spaces", "does-not-exist") is None
    assert spaces_repo.find_id(board_id, "garbage", "x") is None


def test_update_prompt_round_trips_to_db(isolated_repo, seeded_board, board_id):
    from sqlalchemy import select
    from domains.spaces import repository as spaces_repo

    assert spaces_repo.update_prompt(board_id, "spaces", "corner_tl", "shiny new prompt") is True
    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "perimeter",
                CellRecord.slug == "corner_tl",
            )
        )
        assert row is not None
        assert row.prompt == "shiny new prompt"


def test_update_space_kind_validates_value(isolated_repo, seeded_board, board_id):
    from domains.spaces import repository as spaces_repo

    assert spaces_repo.update_space_kind(board_id, "corner_tl", "event") is True
    assert spaces_repo.update_space_kind(board_id, "corner_tl", "standard") is True
    with pytest.raises(ValueError):
        spaces_repo.update_space_kind(board_id, "corner_tl", "garbage")
    assert spaces_repo.update_space_kind(board_id, "missing-slug", "event") is False


def test_save_catalog_preserves_cell_ids_for_unchanged_cells(
    isolated_repo, seeded_board, board_id,
):
    """``_replace_cells`` must keep ``cells.id`` stable across a no-op save
    so ``asset_versions.cell_id`` survives a board edit. Regression guard for
    the asset history → cell linkage."""
    from domains.spaces import repository as spaces_repo
    from domains.boards import services as svc_catalog

    before = {(c.kind, c.slug): c.id for c in spaces_repo.list_for_board(board_id)}
    cat = svc_catalog.load_catalog(board_id)
    cat["project"] = cat["project"]  # round-trip without semantic change
    svc_catalog.save_catalog(board_id, cat)
    after = {(c.kind, c.slug): c.id for c in spaces_repo.list_for_board(board_id)}
    assert before == after, "cell IDs changed across a no-op save"

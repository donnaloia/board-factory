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


def test_persist_catalog_dict_preserves_cell_ids_for_unchanged_cells(
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
    svc_catalog.persist_catalog_dict(board_id, cat)
    after = {(c.kind, c.slug): c.id for c in spaces_repo.list_for_board(board_id)}
    assert before == after, "cell IDs changed across a no-op save"


def test_prune_cell_files_removes_live_history_and_asset_versions(
    isolated_repo, seeded_board, board_id,
):
    """``prune_cell_files`` must remove every disk + DB artifact for one cell."""
    from sqlalchemy import insert, select

    from infrastructure import board_store as bs
    from domains.spaces.assets.models import AssetVersionRecord
    from domains.spaces import repository as spaces_repo

    store = bs.get_store()
    cell_id = spaces_repo.find_id(board_id, "spaces", "corner_tl")
    assert cell_id is not None

    store.write_bytes(board_id, "workspace/live/spaces/corner_tl.png", b"\x89PNG-live")
    store.write_bytes(
        board_id, "workspace/history/spaces/corner_tl/1700000000001__001.png", b"\x89PNG-h1"
    )
    store.write_bytes(
        board_id, "workspace/history/spaces/corner_tl/1700000000002__002.png", b"\x89PNG-h2"
    )
    with session_scope() as session:
        session.execute(
            insert(AssetVersionRecord).values(
                board_uuid=board_id,
                cell_id=cell_id,
                category="spaces",
                asset_id="corner_tl",
                basename="1700000000001__001.png",
                rel_path="history/spaces/corner_tl/1700000000001__001.png",
                ts_ms=1700000000001,
            )
        )

    stats = spaces_repo.prune_cell_files(board_id, "spaces", "corner_tl")

    assert stats["live_files"] == 1
    assert stats["history_files"] == 2
    assert stats["asset_version_rows"] == 1
    assert not store.exists(board_id, "workspace/live/spaces/corner_tl.png")
    assert store.list(board_id, "workspace/history/spaces/corner_tl") == []

    with session_scope() as session:
        remaining = session.scalars(
            select(AssetVersionRecord).where(
                AssetVersionRecord.board_uuid == board_id,
                AssetVersionRecord.asset_id == "corner_tl",
            )
        ).all()
    assert remaining == []


def test_prune_cell_files_is_idempotent(isolated_repo, seeded_board, board_id):
    """Running the prune twice must not raise; second call returns zeros."""
    from domains.spaces import repository as spaces_repo

    spaces_repo.prune_cell_files(board_id, "spaces", "corner_tl")
    second = spaces_repo.prune_cell_files(board_id, "spaces", "corner_tl")
    assert second == {
        "animations_rows": 0,
        "animation_files": 0,
        "asset_version_rows": 0,
        "live_files": 0,
        "history_files": 0,
    }


def test_prune_cell_files_unknown_category_raises(seeded_board, board_id):
    from domains.spaces import repository as spaces_repo

    with pytest.raises(ValueError, match="unknown category"):
        spaces_repo.prune_cell_files(board_id, "tokens", "irrelevant")

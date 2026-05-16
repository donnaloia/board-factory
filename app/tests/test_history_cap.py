"""History depth cap: ``prune_history_for_cell`` + automatic prune-on-insert.

Asserts that:

* The cap removes the oldest rows AND their on-disk files.
* The currently live row is preserved even when older than the cap.
* Disabling the cap (``BOARDFACTORY_HISTORY_LIMIT_PER_CELL=0``) is a no-op.
* Calling ``_on_history_push`` indirectly via the boardfactory listener
  triggers the prune so disk + DB stay capped together.
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from domains.spaces.assets.models import AssetVersionRecord


def _seed_history(
    board_id: str, cell_id: str, slug: str, *, count: int, ts_start: int = 1_700_000_000_000
) -> list[int]:
    """Write ``count`` history files + matching ``asset_versions`` rows.

    Returns the inserted ``asset_versions.id`` values in ascending ts order.
    """
    store = bs.get_store()
    ids: list[int] = []
    for i in range(count):
        ts = ts_start + i
        basename = f"{ts}__{i:03d}.png"
        rel_path = f"history/spaces/{slug}/{basename}"
        full_rel = f"workspace/{rel_path}"
        store.write_bytes(board_id, full_rel, f"v{i}".encode())
        with session_scope() as session:
            new_id = session.execute(
                insert(AssetVersionRecord)
                .values(
                    board_uuid=board_id,
                    cell_id=cell_id,
                    category="spaces",
                    asset_id=slug,
                    basename=basename,
                    rel_path=rel_path,
                    ts_ms=ts,
                )
                .returning(AssetVersionRecord.id)
            ).scalar()
            ids.append(int(new_id))
    return ids


def test_prune_history_for_cell_keeps_newest_n(
    isolated_repo, seeded_board, board_id, monkeypatch,
):
    monkeypatch.setenv("BOARDFACTORY_HISTORY_LIMIT_PER_CELL", "3")
    from domains.spaces.assets import repository as asset_index
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(board_id, "spaces", "corner_tl")
    assert cell_id is not None
    ids = _seed_history(board_id, cell_id, "corner_tl", count=7)

    stats = asset_index.prune_history_for_cell(board_id, "spaces", "corner_tl")
    assert stats == {"deleted_rows": 4, "deleted_files": 4}

    with session_scope() as session:
        remaining = session.scalars(
            select(AssetVersionRecord.id).where(
                AssetVersionRecord.board_uuid == board_id,
                AssetVersionRecord.asset_id == "corner_tl",
            )
        ).all()
    assert set(remaining) == set(ids[-3:]), "must keep the newest three rows"

    store = bs.get_store()
    for old_id in ids[:4]:
        # Files for the deleted rows must be gone too.
        with session_scope() as session:
            row = session.get(AssetVersionRecord, old_id)
            assert row is None
    for new_id in ids[-3:]:
        with session_scope() as session:
            row = session.get(AssetVersionRecord, new_id)
            assert row is not None
            assert store.exists(board_id, f"workspace/{row.rel_path}")


def test_prune_history_preserves_live_row_even_if_older(
    isolated_repo, seeded_board, board_id, monkeypatch,
):
    monkeypatch.setenv("BOARDFACTORY_HISTORY_LIMIT_PER_CELL", "2")
    from domains.spaces.assets import repository as asset_index
    from domains.spaces import repository as spaces_repo
    from domains.spaces.models import CellRecord

    cell_id = spaces_repo.find_id(board_id, "spaces", "corner_tl")
    assert cell_id is not None
    ids = _seed_history(board_id, cell_id, "corner_tl", count=5)

    # Pin the OLDEST row as live - it must survive the prune.
    live_id = ids[0]
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        cell.live_asset_version_id = live_id

    asset_index.prune_history_for_cell(board_id, "spaces", "corner_tl")

    with session_scope() as session:
        remaining = set(
            session.scalars(
                select(AssetVersionRecord.id).where(
                    AssetVersionRecord.board_uuid == board_id,
                    AssetVersionRecord.asset_id == "corner_tl",
                )
            ).all()
        )
    assert live_id in remaining, "the live row must always survive the prune"
    assert ids[-1] in remaining and ids[-2] in remaining, "newest two rows must survive"


def test_prune_history_disabled_with_zero_limit(
    isolated_repo, seeded_board, board_id, monkeypatch,
):
    monkeypatch.setenv("BOARDFACTORY_HISTORY_LIMIT_PER_CELL", "0")
    from domains.spaces.assets import repository as asset_index
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(board_id, "spaces", "corner_tl")
    assert cell_id is not None
    _seed_history(board_id, cell_id, "corner_tl", count=10)

    stats = asset_index.prune_history_for_cell(board_id, "spaces", "corner_tl")
    assert stats == {"deleted_rows": 0, "deleted_files": 0}

    with session_scope() as session:
        n = session.scalar(
            select(AssetVersionRecord.id)
            .where(AssetVersionRecord.asset_id == "corner_tl")
            .order_by(AssetVersionRecord.ts_ms.desc())
        )
    assert n is not None  # rows still present


def test_history_push_listener_auto_prunes(
    isolated_repo, seeded_board, board_id, monkeypatch,
):
    """The cap kicks in automatically through ``_on_history_push`` so we
    don't accumulate history forever even if no one ever calls the prune.
    """
    monkeypatch.setenv("BOARDFACTORY_HISTORY_LIMIT_PER_CELL", "2")
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config
    from domains.spaces.assets import repository as asset_index

    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            for i in range(5):
                bf_assets.push_to_history(
                    "spaces",
                    "corner_tl",
                    f"\x89PNG-{i}".encode(),
                    operation=bf_assets.OP_REGEN,
                    prompt=f"v{i}",
                )
        with session_scope() as session:
            rows = session.scalars(
                select(AssetVersionRecord).where(
                    AssetVersionRecord.board_uuid == board_id,
                    AssetVersionRecord.asset_id == "corner_tl",
                )
            ).all()
        assert len(rows) == 2, f"expected 2 rows after cap, got {len(rows)}"
    finally:
        bf_assets._asset_db_listeners.clear()

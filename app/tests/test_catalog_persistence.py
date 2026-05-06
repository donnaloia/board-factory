"""Catalog persistence (board_games row + body_json) + asset index integration."""

from __future__ import annotations

from sqlalchemy import select

from infrastructure.db import session_scope
from assets.models import AssetVersionRecord
from domains.boards.models import BoardGameRecord


def test_catalog_persists_to_board_games(isolated_repo, seeded_board, board_id):
    from domains.boards import services as svc_catalog
    from domains.cells.models import CellRecord

    data = svc_catalog.load_catalog(board_id)
    assert data.get("project") == "Test Board"
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert bg.project == "Test Board"
        assert bg.style_reference_image  # populated from the seeded catalog
        # body_json holds only the perimeter ``board_spaces.layout`` map.
        assert set(bg.body_json.keys()) == {"board_spaces"}
        assert set(bg.body_json["board_spaces"].keys()) == {"layout"}
        # Cells (designs / panels / centerpiece) live in ``cells``.
        kinds = {c.kind for c in session.query(CellRecord)
                                          .filter(CellRecord.board_uuid == board_id).all()}
        assert kinds == {"space", "panel", "centerpiece"}


def test_save_catalog_updates_db(isolated_repo, seeded_board, board_id):
    from domains.boards import services as svc_catalog

    cat = svc_catalog.load_catalog(board_id)
    cat["project"] = "Saved Via DB"
    svc_catalog.save_catalog(board_id, cat)
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert bg.project == "Saved Via DB"


def test_asset_index_counts_history_push(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    from assets import repository as asset_index

    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            # Use a slug from the seeded catalog so the cells FK resolves.
            bf_assets.push_to_history(
                "spaces",
                "corner_tl",
                b"\x89PNG\r\n\x1a\n\x00\x00",
                operation=bf_assets.OP_REGEN,
                prompt="x",
            )
        n = asset_index.count_for_cell(board_id, "spaces", "corner_tl")
        assert n >= 1
    finally:
        bf_assets._asset_db_listeners.clear()


def test_promote_copies_history_to_live(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    from assets import repository as asset_index
    from infrastructure.files import workspace as fs_ws

    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            out = bf_assets.push_to_history(
                "spaces",
                "corner_tr",
                b"\x89PNG\r\n\x1a\n\x00\x00",
                operation=bf_assets.OP_REGEN,
                prompt="hello",
            )
            bf_assets.promote("spaces", "corner_tr", out.name)
            meta = bf_assets.read_meta("spaces", "corner_tr", out.name)
        live = fs_ws.live_path(board_id, "spaces", "corner_tr")
        assert live.exists()
        history = fs_ws.history_dir(board_id, "spaces", "corner_tr") / out.name
        assert live.read_bytes() == history.read_bytes()
        assert meta.get("prompt") == "hello"
    finally:
        bf_assets._asset_db_listeners.clear()


def test_asset_backfill_inserts_rows(isolated_repo, seeded_board, board_id):
    from assets import repository as asset_index
    from infrastructure import board_store as bs
    from infrastructure.files import workspace as fs_ws

    # Use a cell from the seeded catalog so the FK resolves; legacy orphan
    # files (cells deleted but PNGs kept) are skipped, not counted.
    bs.get_store().write_bytes(
        board_id,
        "workspace/history/panels/panel_left_top/9000000000000__001.png",
        b"\x89PNG\r\n\x1a\n",
    )
    assert (
        fs_ws.history_dir(board_id, "panels", "panel_left_top") / "9000000000000__001.png"
    ).exists()

    asset_index.backfill_board(board_id)
    with session_scope() as session:
        q = select(AssetVersionRecord).where(
            AssetVersionRecord.board_uuid == board_id,
            AssetVersionRecord.basename == "9000000000000__001.png",
        )
        assert session.scalars(q).first() is not None

"""Phase 3–5 integration: DB catalog + asset index rows."""

from __future__ import annotations

from sqlalchemy import select

from storage.db import session_scope
from models.core import AssetVersionRecord, BoardGameRecord


def test_catalog_persists_to_board_games(isolated_repo, seeded_board, board_id):
    import json

    from services import catalog as svc_catalog

    data = svc_catalog.load_catalog(board_id)
    assert data.get("project") == "Test Board"
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert json.loads(bg.body_json)["project"] == "Test Board"


def test_yaml_disk_edit_requires_explicit_sync(isolated_repo, seeded_board, board_id):
    from services import catalog as svc_catalog
    from storage.fs import workspace as fs_ws
    from storage.fs import yaml_io as fs_yaml

    data = svc_catalog.load_catalog(board_id)
    # Legacy shadow copy on disk (not used at runtime while DB has rows).
    fs_yaml.save_yaml_atomic(fs_ws.catalog_path(board_id), dict(data))

    svc_catalog.load_catalog(board_id)
    ypath = fs_ws.catalog_path(board_id)
    text = ypath.read_text()
    ypath.write_text(text.replace("Test Board", "Renamed Board"))
    # Relational row is still canonical until we explicitly re-import the file.
    assert svc_catalog.safe_load_catalog(board_id).get("project") == "Test Board"
    svc_catalog.sync_disk_yaml_into_relational(board_id)
    assert svc_catalog.safe_load_catalog(board_id).get("project") == "Renamed Board"


def test_save_catalog_updates_db(isolated_repo, seeded_board, board_id):
    import json

    from services import catalog as svc_catalog

    cat = svc_catalog.load_catalog(board_id)
    cat["project"] = "Saved Via DB"
    svc_catalog.save_catalog(board_id, cat)
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert json.loads(bg.body_json)["project"] == "Saved Via DB"


def test_asset_index_counts_history_push(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    from services import asset_index

    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            bf_assets.push_to_history(
                "spaces",
                "dummy-space",
                b"\x89PNG\r\n\x1a\n\x00\x00",
                operation=bf_assets.OP_REGEN,
                prompt="x",
            )
        n = asset_index.count_for_cell(board_id, "spaces", "dummy-space")
        assert n >= 1
    finally:
        bf_assets._asset_db_listeners.clear()


def test_promote_copies_history_to_live(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    from services import asset_index
    from storage.fs import workspace as fs_ws

    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            out = bf_assets.push_to_history(
                "spaces",
                "slot-a",
                b"\x89PNG\r\n\x1a\n\x00\x00",
                operation=bf_assets.OP_REGEN,
                prompt="hello",
            )
            bf_assets.promote("spaces", "slot-a", out.name)
            meta = bf_assets.read_meta("spaces", "slot-a", out.name)
        live = fs_ws.live_path(board_id, "spaces", "slot-a")
        assert live.exists()
        history = fs_ws.history_dir(board_id, "spaces", "slot-a") / out.name
        assert live.read_bytes() == history.read_bytes()
        assert meta.get("prompt") == "hello"
    finally:
        bf_assets._asset_db_listeners.clear()


def test_asset_backfill_inserts_rows(isolated_repo, seeded_board, board_id):
    from services import asset_index
    from storage import board_store as bs
    from storage.fs import workspace as fs_ws

    bs.get_store().write_bytes(
        board_id,
        "workspace/history/panels/p1/9000000000000__001.png",
        b"\x89PNG\r\n\x1a\n",
    )
    # Sanity: the path the backfill scans matches what the store wrote.
    assert (fs_ws.history_dir(board_id, "panels", "p1") / "9000000000000__001.png").exists()

    asset_index.backfill_board(board_id)
    with session_scope() as session:
        q = select(AssetVersionRecord).where(
            AssetVersionRecord.board_id == board_id,
            AssetVersionRecord.basename == "9000000000000__001.png",
        )
        assert session.scalars(q).first() is not None

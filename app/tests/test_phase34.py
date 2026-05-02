"""Phase 3–5 integration: DB catalog + asset index rows."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from storage.db import session_scope
from storage.models.core import AssetVersionRecord, BoardCatalogRecord, BoardGameRecord


def test_catalog_migrates_yaml_to_db(isolated_repo, seeded_board, board_id):
    from services import catalog as svc_catalog

    data = svc_catalog.load_catalog(board_id)
    assert data.get("project") == "Test Board"
    with session_scope() as session:
        row = session.get(BoardCatalogRecord, board_id)
        assert row is not None
        assert "Test Board" in row.body_json
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert bg.project == "Test Board"


def test_yaml_disk_edit_requires_explicit_sync(isolated_repo, seeded_board, board_id):
    from services import catalog as svc_catalog
    from storage.fs import workspace as fs_ws
    from storage.fs import yaml_io as fs_yaml

    data = svc_catalog.load_catalog(board_id)
    # Legacy shadow copy on disk (not used at runtime while DB has rows).
    fs_yaml.save_yaml_atomic(fs_ws.catalog_path(board_id), dict(data))

    svc_catalog.load_catalog(board_id)
    ypath = Path(isolated_repo) / "boards" / board_id / "catalog.yml"
    text = ypath.read_text()
    ypath.write_text(text.replace("Test Board", "Renamed Board"))
    # Relational row is still canonical until we explicitly re-import the file.
    assert svc_catalog.safe_load_catalog(board_id).get("project") == "Test Board"
    svc_catalog.sync_disk_yaml_into_relational(board_id)
    assert svc_catalog.safe_load_catalog(board_id).get("project") == "Renamed Board"


def test_save_catalog_updates_db(isolated_repo, seeded_board, board_id):
    from services import catalog as svc_catalog

    cat = svc_catalog.load_catalog(board_id)
    cat["project"] = "Saved Via DB"
    svc_catalog.save_catalog(board_id, cat)
    with session_scope() as session:
        row = session.get(BoardCatalogRecord, board_id)
        assert row is not None
        assert "Saved Via DB" in row.body_json
        bg = session.get(BoardGameRecord, board_id)
        assert bg is not None
        assert bg.project == "Saved Via DB"


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


def test_promote_persists_asset_live_pointer(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    from services import asset_index
    from services.asset_live import get_live_rel_path

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
        rel = get_live_rel_path(board_id, "spaces", "slot-a")
        assert rel == f"history/spaces/slot-a/{out.name}"
        assert meta.get("prompt") == "hello"
    finally:
        bf_assets._asset_db_listeners.clear()


def test_asset_backfill_inserts_rows(isolated_repo, seeded_board, board_id):
    from boardfactory import assets as bf_assets
    from boardfactory import config as bf_config

    hist_root = Path(isolated_repo) / "boards" / board_id / "workspace" / "history" / "panels" / "p1"
    hist_root.mkdir(parents=True, exist_ok=True)
    png = hist_root / "9000000000000__001.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    from services import asset_index

    asset_index.backfill_board(board_id)
    with session_scope() as session:
        q = select(AssetVersionRecord).where(
            AssetVersionRecord.board_id == board_id,
            AssetVersionRecord.basename == png.name,
        )
        assert session.scalars(q).first() is not None

"""Promotion pointer + ``active_prompt`` resolution (issue #6)."""

from __future__ import annotations

from boardfactory import assets as bf_assets
from boardfactory import config as bf_config

from routes import deps
from assets import repository as asset_index
from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws


def test_promote_writes_live_source_pointer(isolated_repo, seeded_board, board_id):
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
        rel = fs_ws.live_source_rel("spaces", "slot-a")
        assert bs.get_store().exists(board_id, rel)
        raw = bs.get_store().read_bytes(board_id, rel).decode()
        assert out.name in raw
    finally:
        bf_assets._asset_db_listeners.clear()


def test_active_prompt_matches_promoted_history_row(isolated_repo, seeded_board, board_id):
    """Older history row with a distinct prompt wins via pointer, not byte-match order."""
    bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    try:
        with bf_config.scope_board(board_id):
            out_old = bf_assets.push_to_history(
                "spaces",
                "corner_tl",
                b"\x89PNG\r\n\x1a\n\x01\x01",
                operation=bf_assets.OP_REGEN,
                prompt="from older generation",
            )
            bf_assets.push_to_history(
                "spaces",
                "corner_tl",
                b"\x89PNG\r\n\x1a\n\x02\x02",
                operation=bf_assets.OP_REGEN,
                prompt="from newer generation",
            )
            bf_assets.promote("spaces", "corner_tl", out_old.name)

        payload = deps.build_cell_side_panel_payload(board_id, "spaces", "corner_tl")
        assert payload["active_prompt"] == "from older generation"
        assert payload["live_history_filename"] == out_old.name
    finally:
        bf_assets._asset_db_listeners.clear()

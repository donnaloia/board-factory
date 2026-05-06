"""Promotion + ``active_prompt`` resolution (DB-backed ``live_asset_version_id``)."""

from __future__ import annotations

from boardfactory import assets as bf_assets
from boardfactory import config as bf_config

from infrastructure import deps
from assets import repository as asset_index


def test_active_prompt_matches_promoted_history_row(isolated_repo, seeded_board, board_id):
    """Older history row with a distinct prompt wins via DB FK + promote, not byte-match order."""
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
        assert payload["live_asset_version_id"] is not None
    finally:
        bf_assets._asset_db_listeners.clear()

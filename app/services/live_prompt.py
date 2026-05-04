"""Resolve the sidebar ``active_prompt`` for one cell.

Priority:

1. **Promotion pointer** (``workspace/meta/live_source/…``) — prompt from that
   history file's metadata (same source as user clicked to promote).
2. **Legacy**: history rows whose bytes match live (``is_live``), newest-first;
   use the first row that has a stored prompt.
3. **Catalog default** when nothing else applies — never invent a prompt from
   an unrelated history row (removed fallback that picked “newest with any prompt”).
"""

from __future__ import annotations

from typing import Any

from boardfactory import assets as bf_assets
from boardfactory import config as bf_config

from services import live_source as live_source_svc


def resolve_active_prompt(
    board_id: str,
    category: str,
    asset_id: str,
    *,
    entries: list[Any],
    catalog_prompt: str,
) -> str:
    """``entries`` are :class:`boardfactory.assets.HistoryEntry` (newest-first)."""

    ptr = live_source_svc.read_live_source(board_id, category, asset_id)
    if ptr is not None:
        with bf_config.set_active_board(board_id):
            meta = bf_assets.read_meta(category, asset_id, ptr.history_filename)
        p = meta.get("prompt")
        if p is not None:
            return p
        # Same basename as list_history() — metadata merge can differ from read_meta
        # in edge cases; prefer the entry row's prompt when present.
        for e in entries:
            if e.filename == ptr.history_filename and e.prompt is not None:
                return e.prompt
        # Pointer names a clean/migrated row with no prompt — fall through.

    for e in entries:
        if not e.is_live:
            continue
        if e.prompt is not None:
            return e.prompt

    return catalog_prompt

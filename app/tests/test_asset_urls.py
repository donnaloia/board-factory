"""Contract tests for :mod:`services.asset_urls` (cache-bust query format)."""

from __future__ import annotations

import re

from services import asset_urls


def test_board_asset_url_uses_millis_not_seconds():
    url = asset_urls.board_asset_url(
        http_prefix="/u/game",
        asset_relpath="live/spaces/x.png",
        mtime_ms=1_700_000_000_123,
    )
    assert url == "/u/game/asset/live/spaces/x.png?t=1700000000123"
    m = re.search(r"[?&]t=(\d+)$", url)
    assert m and len(m.group(1)) >= 10  # ms epoch, not 10-digit seconds bucket


def test_board_asset_url_normalizes_prefix_and_path():
    assert asset_urls.board_asset_url(
        http_prefix="/prefix/",
        asset_relpath="/live/a.png",
        mtime_ms=99,
    ) == "/prefix/asset/live/a.png?t=99"


def test_mtime_ms_from_path_roundtrip(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"x")
    ms = asset_urls.mtime_ms_from_path(p)
    assert isinstance(ms, int)
    assert ms > 1_000_000_000_000


def test_wall_clock_ms_monotonic():
    a = asset_urls.wall_clock_ms()
    b = asset_urls.wall_clock_ms()
    assert b >= a
    assert len(str(a)) >= 13

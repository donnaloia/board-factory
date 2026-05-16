"""URL helpers for board workspace files (``/asset/…`` under a board prefix).

Currently URL builders. The DB index sits in :mod:`domains.spaces.assets.repository` and
the on-disk file plumbing lives in ``infrastructure.board_store``; this
module is the thin glue that other domains (views, routes) reach for
when they need a stable, cache-busted ``/asset/...`` link.

Public API
----------

``board_asset_url``
    Build ``{prefix}/asset/{path}?t={mtime_ms}``.

``mtime_ms_from_path``
    When you already have a :class:`pathlib.Path` and no board store in scope.

``wall_clock_ms``
    Ephemeral bust token for non-file-backed URLs.

URL contract
------------

Every ``/asset/...`` link that reflects an on-disk file under the board
store should include ``?t=<mtime_ms>`` where ``mtime_ms`` matches
``FileStat.mtime_ms`` (:func:`infrastructure.board_store.BoardStore.stat`).
Use **milliseconds**, not seconds: truncating mtime caused stale tiles
after promote when the deferred board SVG refresh reused the same ``?t``
within one POSIX second.

For routes that are not tied to one store file (e.g. composed
``frame.png``), use :func:`wall_clock_ms` so the query param stays
numeric ms without overloading file-mtime semantics.
"""

from __future__ import annotations

import time
from pathlib import Path


def board_asset_url(*, http_prefix: str, asset_relpath: str, mtime_ms: int) -> str:
    """Return ``http_prefix/asset/<relpath>?t=<mtime_ms>``.

    ``asset_relpath`` is the path segment after ``/asset/`` (no leading slash),
    e.g. ``live/spaces/corner_tl.png`` — same string used in routes and
    ``live_rel(...).removeprefix("workspace/")``.
    """
    rel = asset_relpath.replace("\\", "/").lstrip("/")
    base = http_prefix.rstrip("/")
    return f"{base}/asset/{rel}?t={int(mtime_ms)}"


def mtime_ms_from_path(path: Path) -> int:
    """Millisecond mtime for a local file; shape matches ``FileStat.mtime_ms``."""
    return int(path.stat().st_mtime * 1000)


def wall_clock_ms() -> int:
    """Milliseconds since epoch; for cache-busting URLs not keyed by store mtime."""
    return int(time.time() * 1000)

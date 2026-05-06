"""Per-asset history + live management for the web app.

The classic pipeline writes candidates → cleaned → approved as three
distinct stages with manual approval in between. The web app instead
treats each cell on the board as a single asset slot with two pieces of
state on disk:

- workspace/live/<category>/<asset_id>.png      ← what's currently shown
- ``workspace/history/…``        — every version ever made

Promotion updates ``cells.live_asset_version_id`` in Postgres via the
registered ``live_promote`` listener (see web ``assets.repository``).
Generation auto-promotes the newest output as live; the user can scroll
the history strip to flip back to any prior version (just copies that
file back to live/<asset_id>.png).

Centerpiece is treated as asset_id="centerpiece" in category="centerpiece"
so the same primitives work for it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config


_asset_db_listeners: list[Callable[..., None]] = []


def register_asset_db_listener(fn: Callable[..., None]) -> None:
    """Services layer registers DB-backed asset index hooks (optional — empty by default)."""
    _asset_db_listeners.append(fn)


def _notify_asset_db(kind: str, **kwargs: Any) -> None:
    if not _asset_db_listeners:
        return
    bid = config.active_board()
    if not bid:
        return
    for cb in list(_asset_db_listeners):
        try:
            cb(kind, board_id=bid, **kwargs)
        except Exception:
            pass


# Note: do not bind HISTORY_DIR / LIVE_DIR at import time — they would lock to
# whichever board was active at import. Always resolve via config.HISTORY_DIR
# / config.LIVE_DIR (lazy via config.__getattr__) so these always reflect the
# currently-active board.


# ────────────────────────── operation kinds ──────────────────────────


# What produced a history entry. Used by the side panel to label each row
# and to decide whether to restore the prompt.
OP_REGEN = "regen"          # provider call with a prompt
OP_CLEAN = "clean"          # palette quantize + grid snap of the live image


# ────────────────────────── path helpers ──────────────────────────


def history_dir(category: str, asset_id: str) -> Path:
    return config.HISTORY_DIR / category / asset_id


def live_path(category: str, asset_id: str) -> Path:
    """Canonical on-disk path for a cell's live image (``live/<cat>/<id>.png``).

    Tracked by git so a fresh clone reproduces the board grid.
    """
    if category == "centerpiece":
        return config.LIVE_DIR / "centerpiece" / "centerpiece.png"
    return config.LIVE_DIR / category / f"{asset_id}.png"


def has_live(category: str, asset_id: str) -> bool:
    return live_path(category, asset_id).exists()


# ────────────────────────── write ──────────────────────────


def push_to_history(
    category: str,
    asset_id: str,
    png_bytes: bytes,
    *,
    operation: str = OP_REGEN,
    prompt: str | None = None,
    extras: dict | None = None,
) -> Path:
    """Write a new PNG into history and notify the asset index. Returns its path.

    Metadata is recorded in the database via the registered listener
    (``asset_versions.meta_json``). Legacy ``.meta.json`` sidecars are no
    longer written for new entries.

    Caller decides whether to also call promote() to make this entry live.
    """
    d = history_dir(category, asset_id)
    d.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    seq = len(list(d.glob("*.png"))) + 1
    out = d / f"{ts}__{seq:03d}.png"
    out.write_bytes(png_bytes)

    meta = {
        "operation": operation,
        "prompt": prompt,
        "ts_ms": ts,
        "seq": seq,
    }
    if extras:
        meta["extras"] = extras
    try:
        rel = str(out.relative_to(config.WORKSPACE)).replace("\\", "/")
    except ValueError:
        rel = f"history/{category}/{asset_id}/{out.name}"
    _notify_asset_db(
        "history_push",
        category=category,
        asset_id=asset_id,
        basename=out.name,
        rel_path=rel,
        sha256=hashlib.sha256(png_bytes).hexdigest(),
        ts_ms=ts,
        meta_json=json.dumps(meta),
    )
    return out


def read_meta(category: str, asset_id: str, history_filename: str) -> dict:
    """Return metadata for one history entry (merge DB ``meta_json`` + legacy sidecar).

    New history rows record metadata only in the database. Legacy boards may
    still have ``.meta.json`` sidecars; if the DB row exists but omits
    ``prompt`` (index gaps, partial rows), a sidecar prompt is still visible.
    """
    hist_dir = history_dir(category, asset_id)
    sidecar = (hist_dir / history_filename).with_suffix(".meta.json")
    fs_meta: dict = {}
    if sidecar.exists():
        try:
            fs_meta = json.loads(sidecar.read_text())
        except Exception:
            fs_meta = {}

    db_meta: dict | None = None
    bid = config.active_board()
    if bid:
        try:
            from assets.repository import read_meta as read_meta_from_db

            db_meta = read_meta_from_db(bid, category, asset_id, history_filename)
        except Exception:
            db_meta = None

    if db_meta:
        merged = {**fs_meta, **db_meta}
        if merged.get("prompt") is None and fs_meta.get("prompt"):
            merged["prompt"] = fs_meta["prompt"]
        return merged
    return fs_meta if fs_meta else {}


def promote(category: str, asset_id: str, history_filename: str) -> Path:
    """Copy a specific history file to ``live/<cat>/<id>.png``. Returns the live path.

    history_filename is just the basename (e.g. '1735012345__001.png').
    """
    src = history_dir(category, asset_id) / history_filename
    if not src.exists():
        raise FileNotFoundError(f"No history entry {src}")
    dst = live_path(category, asset_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    _notify_asset_db(
        "live_promote",
        category=category,
        asset_id=asset_id,
        history_filename=history_filename,
    )
    return dst


def clear_live(category: str, asset_id: str) -> None:
    p = live_path(category, asset_id)
    if p.exists():
        p.unlink()


# ────────────────────────── read ──────────────────────────


@dataclass(frozen=True)
class HistoryEntry:
    filename: str           # e.g. "1735012345__001.png"
    timestamp_ms: int       # parsed from filename
    seq: int                # parsed from filename
    is_live: bool           # bytes match the current live file
    operation: str          # OP_REGEN | OP_CLEAN
    prompt: str | None      # the prompt used (None for clean)


def list_history(category: str, asset_id: str) -> list[HistoryEntry]:
    """Newest-first list of every history entry for this asset, with metadata."""
    d = history_dir(category, asset_id)
    if not d.exists():
        return []
    live_bytes: bytes | None = None
    lp = live_path(category, asset_id)
    if lp.exists():
        try:
            live_bytes = lp.read_bytes()
        except OSError:
            live_bytes = None

    entries: list[HistoryEntry] = []
    for p in d.glob("*.png"):
        name = p.name
        ts_str, _, rest = name.partition("__")
        seq_str = rest.replace(".png", "")
        try:
            ts_ms = int(ts_str)
            seq = int(seq_str)
        except ValueError:
            continue
        is_live = False
        if live_bytes is not None:
            try:
                is_live = p.read_bytes() == live_bytes
            except OSError:
                is_live = False
        meta = read_meta(category, asset_id, name)
        entries.append(HistoryEntry(
            filename=name,
            timestamp_ms=ts_ms,
            seq=seq,
            is_live=is_live,
            operation=meta.get("operation", OP_REGEN),
            prompt=meta.get("prompt"),
        ))
    entries.sort(key=lambda e: (e.timestamp_ms, e.seq), reverse=True)
    return entries


# ────────────────────────── re-cleanup (free, no provider) ──────────────────────────


# Imported lazily inside the function so this module stays cheap to import
# (the steps modules pull in the rich-free pipeline; we want no cycles).


def reclean_live(category: str, asset_id: str) -> str | None:
    """Re-run pixel cleanup on the current live image, push the result to
    history with operation=clean, and promote it as the new live.

    Returns the basename of the new history entry on success. Raises if
    there's no palette yet (style step hasn't been run) or no live image to
    clean.

    Free, fast, no provider call. Used by the "Cleanup image" side-panel
    action — useful when the palette changed after the asset was generated
    or when the asset is one quantize pass away from looking right.
    """
    from .palette import load_palette

    pal_path = config.STYLE_DIR / "palette.json"
    if not pal_path.exists():
        raise RuntimeError(
            "No palette found. Run the style step first so cleanup has a target palette."
        )
    palette = load_palette(pal_path)

    live = live_path(category, asset_id)
    if not live.exists():
        raise RuntimeError(
            f"No live image to clean for {category}/{asset_id}. Generate one first."
        )

    # Lazy import to avoid pulling the ops package eagerly.
    from .ops.draw_cell import _cleanup_one
    cleaned = _cleanup_one(live.read_bytes(), palette)

    out = push_to_history(
        category, asset_id, cleaned,
        operation=OP_CLEAN,
        prompt=None,
        extras={"palette_size": len(palette)},
    )
    promote(category, asset_id, out.name)
    return out.name

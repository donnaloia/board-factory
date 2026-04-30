"""Per-asset history + live management for the web app.

The classic pipeline writes candidates → cleaned → approved as three
distinct stages with manual approval in between. The web app instead
treats each cell on the board as a single asset slot with two pieces of
state on disk:

- workspace/live/<category>/<asset_id>.png      ← what's currently shown
- workspace/history/<category>/<asset_id>/      ← every version ever made
                              <ts>__<seq>.png

Generation auto-promotes the newest output as live; the user can scroll
the history strip to flip back to any prior version (just copies that
file back to live/<asset_id>.png).

Centerpiece is treated as asset_id="centerpiece" in category="centerpiece"
so the same primitives work for it.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import config


# Note: do not bind HISTORY_DIR / LIVE_DIR at import time — they would lock to
# whichever board was active at import. Always resolve via config.HISTORY_DIR
# / config.LIVE_DIR (lazy via config.__getattr__) so these always reflect the
# currently-active board.


# ────────────────────────── operation kinds ──────────────────────────


# What produced a history entry. Used by the side panel to label each row
# and to decide whether to restore the prompt.
OP_REGEN = "regen"          # provider call with a prompt
OP_CLEAN = "clean"          # palette quantize + grid snap of the live image
OP_REFINE = "refine"        # masked inpaint
OP_LEGACY = "legacy"        # migrated from the classic approved/ flow


# ────────────────────────── path helpers ──────────────────────────


def history_dir(category: str, asset_id: str) -> Path:
    return config.HISTORY_DIR / category / asset_id


def live_path(category: str, asset_id: str) -> Path:
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
    """Write a new PNG into history with a metadata sidecar, return its path.

    The sidecar lives at <basename>.meta.json and records:
    - operation: one of OP_REGEN | OP_CLEAN | OP_REFINE | OP_LEGACY
    - prompt:    the prompt actually used for this generation (None for clean)
    - ts_ms:     creation time
    - extras:    optional free-form fields (provider name, palette size, etc.)

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
    (out.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=2))
    return out


def read_meta(category: str, asset_id: str, history_filename: str) -> dict:
    """Return the sidecar metadata for one history entry, or an empty dict
    if there is no sidecar (e.g. legacy migrated entries)."""
    d = history_dir(category, asset_id)
    p = (d / history_filename).with_suffix(".meta.json")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def promote(category: str, asset_id: str, history_filename: str) -> Path:
    """Make a specific history file the live asset. Returns the live path.

    history_filename is just the basename (e.g. '1735012345__001.png').
    """
    src = history_dir(category, asset_id) / history_filename
    if not src.exists():
        raise FileNotFoundError(f"No history entry {src}")
    dst = live_path(category, asset_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
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
    operation: str          # OP_REGEN | OP_CLEAN | OP_REFINE | OP_LEGACY
    prompt: str | None      # the prompt used (None for clean / refine)


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
            operation=meta.get("operation", OP_LEGACY),
            prompt=meta.get("prompt"),
        ))
    entries.sort(key=lambda e: (e.timestamp_ms, e.seq), reverse=True)
    return entries


# ────────────────────────── back-compat seeding ──────────────────────────


def seed_from_legacy_approved(category: str, asset_id: str) -> Path | None:
    """If we have an approved/<asset_id>.png from the classic pipeline but
    no live/, copy it into both live/ and history/ so the web app sees it.

    Returns the live path on success, None if nothing to migrate.
    """
    legacy: Path
    if category == "centerpiece":
        legacy = config.APPROVED_DIR / "centerpiece.png"
    else:
        legacy = config.APPROVED_DIR / category / f"{asset_id}.png"

    if not legacy.exists():
        return None
    if has_live(category, asset_id):
        return live_path(category, asset_id)

    raw = legacy.read_bytes()
    push_to_history(category, asset_id, raw, operation=OP_LEGACY, prompt=None)
    dst = live_path(category, asset_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, dst)
    return dst


# ────────────────────────── one-board legacy purge ──────────────────────────


def purge_legacy_dirs() -> list[str]:
    """Delete the active board's legacy `candidates/`, `cleaned/`, `approved/`
    directories. Caller must guarantee everything worth keeping has already
    been seeded into live/ + history/.

    Returns a list of human-readable directory names that were removed. Safe
    to call repeatedly — missing dirs are silently skipped.
    """
    removed: list[str] = []
    workspace = config.WORKSPACE
    for name in ("candidates", "cleaned", "approved"):
        d = workspace / name
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(name)
    return removed


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

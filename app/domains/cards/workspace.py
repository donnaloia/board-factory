"""Filesystem layout for Card Factory deck workspaces.

Each deck lives under ``<CARDFACTORY_DECKS_DIR>/<deck_id>/``.
Default root: ``<BOARDFACTORY_REPO>/data/decks/``, overridable via
``CARDFACTORY_DECKS_DIR``.

Layout per deck::

    <deck_id>/
      frames/
        candidates/
          job_<job_id>/
            candidate_0.png
            candidate_1.png
            candidate_2.png
        committed/
          frame.png          ← copy of chosen candidate
          inner_rect.json    ← pixel-space inner hull {x, y, w, h}
      cards/
        <slot_index>/
          live/
            card.png         ← the one and only card for this slot
          masks/
            m_art.png
            m_stats.png
      prompts.json           ← agent derive-prompts output (cached)

Cards intentionally have **no history**. A slot either has a live PNG (and a
``card_slot_records`` row whose ``live_rel_path`` points at it) or it does
not — regenerating overwrites the live PNG. The DB row + file are the
single source of truth; nothing else may exist on disk for a slot.

All helpers return ``pathlib.Path`` and create parent directories lazily.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


# ────────────────────────── root resolution ──────────────────────────


def _decks_dir() -> Path:
    """Resolve the deck storage root (env-overridable, never cached)."""
    explicit = os.environ.get("CARDFACTORY_DECKS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
    return repo / "data" / "decks"


def deck_root(deck_id: str) -> Path:
    return _decks_dir() / deck_id


# ────────────────────────── frames ──────────────────────────


def frame_candidates_dir(deck_id: str, job_id: str) -> Path:
    d = deck_root(deck_id) / "frames" / "candidates" / f"job_{job_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def frame_candidate_path(deck_id: str, job_id: str, index: int) -> Path:
    return frame_candidates_dir(deck_id, job_id) / f"candidate_{index}.png"


def committed_frame_dir(deck_id: str) -> Path:
    d = deck_root(deck_id) / "frames" / "committed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def committed_frame_path(deck_id: str) -> Path:
    return committed_frame_dir(deck_id) / "frame.png"


def committed_inner_rect_path(deck_id: str) -> Path:
    return committed_frame_dir(deck_id) / "inner_rect.json"


def write_committed_inner_rect(deck_id: str, inner_rect: dict) -> None:
    committed_inner_rect_path(deck_id).write_text(
        json.dumps(inner_rect, indent=2), encoding="utf-8"
    )


def read_committed_inner_rect(deck_id: str) -> dict:
    p = committed_inner_rect_path(deck_id)
    if not p.exists():
        raise FileNotFoundError(f"committed inner_rect missing for deck {deck_id!r}")
    return json.loads(p.read_text("utf-8"))


# ────────────────────────── per-card paths ──────────────────────────


def card_dir(deck_id: str, slot_index: int) -> Path:
    d = deck_root(deck_id) / "cards" / str(slot_index)
    d.mkdir(parents=True, exist_ok=True)
    return d


def card_live_path(deck_id: str, slot_index: int) -> Path:
    d = card_dir(deck_id, slot_index) / "live"
    d.mkdir(parents=True, exist_ok=True)
    return d / "card.png"


def card_masks_dir(deck_id: str, slot_index: int) -> Path:
    d = card_dir(deck_id, slot_index) / "masks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def card_live_rel(slot_index: int) -> str:
    """Forward-slash relative path for the live card PNG (relative to deck root)."""
    return f"cards/{slot_index}/live/card.png"


# ────────────────────────── prompts cache ──────────────────────────


def prompts_cache_path(deck_id: str) -> Path:
    return deck_root(deck_id) / "prompts.json"


def write_prompts_cache(deck_id: str, payloads: list[dict]) -> None:
    deck_root(deck_id).mkdir(parents=True, exist_ok=True)
    prompts_cache_path(deck_id).write_text(
        json.dumps(payloads, indent=2), encoding="utf-8"
    )


def read_prompts_cache(deck_id: str) -> list[dict] | None:
    p = prompts_cache_path(deck_id)
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


# ────────────────────────── lifecycle ──────────────────────────


def create_deck_skeleton(deck_id: str) -> None:
    """Eagerly create the directory tree for a new deck. Idempotent."""
    root = deck_root(deck_id)
    for sub in [
        "frames/candidates",
        "frames/committed",
    ]:
        (root / sub).mkdir(parents=True, exist_ok=True)


def delete_deck_workspace(deck_id: str) -> None:
    """Remove all on-disk files for a deck. Idempotent."""
    import shutil

    root = deck_root(deck_id)
    if root.exists():
        shutil.rmtree(root)

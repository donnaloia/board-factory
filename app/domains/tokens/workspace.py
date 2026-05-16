"""Filesystem layout for Token Factory.

Each token lives in its own top-level directory, independent of any board::

    data/tokens/<token_id>/
      design_lock.json           locomotion, canvas, pivot, clips, token_palette
      references/
        canonical.png            locked static reference (replace = deliberate overwrite)
      candidates/
        candidate_0.png
        candidate_1.png
        candidate_2.png
      clips/
        <clip_name>/
          keys/                  key-pose frames (contact, passing, ...)
            frame_0.png
            frame_2.png
          frames/                final registered frames after inter-frame fill
            frame_0.png
            frame_1.png
            ...
      animations/
        live/                    current promoted atlas + manifest
          atlas.png
          manifest.json
        history/
          <run_id>/              prior full packs for A/B / rollback
            atlas.png
            manifest.json

The on-disk root is configurable via ``BOARDFACTORY_TOKENS_DIR``; the default
is ``<BOARDFACTORY_REPO>/data/tokens/`` — mirroring the Card Factory pattern
under ``data/decks/``. All helpers create parent directories lazily.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


_DEFAULT_TOKENS_SUBDIR = "tokens"


def _tokens_root() -> Path:
    explicit = os.environ.get("BOARDFACTORY_TOKENS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
    return repo / "data" / _DEFAULT_TOKENS_SUBDIR


def token_root(token_id: str) -> Path:
    return _tokens_root() / token_id


# ── design lock ──

def design_lock_path(token_id: str) -> Path:
    return token_root(token_id) / "design_lock.json"


def write_design_lock(token_id: str, data: dict) -> None:
    p = design_lock_path(token_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_design_lock(token_id: str) -> dict | None:
    p = design_lock_path(token_id)
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


# ── references ──

def references_dir(token_id: str) -> Path:
    d = token_root(token_id) / "references"
    d.mkdir(parents=True, exist_ok=True)
    return d


def canonical_png_path(token_id: str) -> Path:
    return references_dir(token_id) / "canonical.png"


def candidates_dir(token_id: str) -> Path:
    d = token_root(token_id) / "candidates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def candidate_path(token_id: str, index: int) -> Path:
    return candidates_dir(token_id) / f"candidate_{index}.png"


# ── clips ──

def clip_dir(token_id: str, clip_name: str) -> Path:
    d = token_root(token_id) / "clips" / clip_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def clip_keys_dir(token_id: str, clip_name: str) -> Path:
    d = clip_dir(token_id, clip_name) / "keys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clip_frames_dir(token_id: str, clip_name: str) -> Path:
    d = clip_dir(token_id, clip_name) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── animations (live / history) ──

def animations_live_dir(token_id: str) -> Path:
    d = token_root(token_id) / "animations" / "live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def animations_history_dir(token_id: str, run_id: str) -> Path:
    d = token_root(token_id) / "animations" / "history" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def live_atlas_path(token_id: str) -> Path:
    return animations_live_dir(token_id) / "atlas.png"


def live_manifest_path(token_id: str) -> Path:
    return animations_live_dir(token_id) / "manifest.json"


def read_live_manifest(token_id: str) -> dict | None:
    p = live_manifest_path(token_id)
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


# ── relative paths (for URL construction) ──
#
# These are forward-slash paths relative to the per-token root. The token
# asset route resolves them under ``data/tokens/<token_id>/<rel>``.

def candidates_rel_prefix() -> str:
    return "candidates"


def candidate_rel(index: int) -> str:
    return f"candidates/candidate_{index}.png"


def canonical_rel() -> str:
    return "references/canonical.png"


def live_atlas_rel() -> str:
    return "animations/live/atlas.png"


def clip_frame_rel(clip_name: str, frame_filename: str) -> str:
    return f"clips/{clip_name}/frames/{frame_filename}"


# ── safe path resolution ──

class PathTraversalError(ValueError):
    """Raised when a token-relative path tries to escape the token root."""


def safe_token_relative(token_id: str, rel: str) -> Path:
    """Resolve ``rel`` underneath ``token_root(token_id)``.

    Raises ``PathTraversalError`` if the resolved path lives outside the
    token directory (e.g. ``../../etc/passwd``).
    """
    root = token_root(token_id).resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise PathTraversalError(
            f"{rel!r} resolves outside the token root"
        ) from e
    return target


# ── lifecycle ──

def create_token_skeleton(token_id: str) -> None:
    """Eagerly create the directory tree for a new token. Idempotent."""
    root = token_root(token_id)
    for sub in ["references", "candidates", "animations/live", "animations/history"]:
        (root / sub).mkdir(parents=True, exist_ok=True)


def delete_token_tree(token_id: str) -> None:
    """Remove the entire on-disk tree for a token. Idempotent."""
    import shutil

    root = token_root(token_id)
    if root.exists():
        shutil.rmtree(root)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]

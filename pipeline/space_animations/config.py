"""Env-driven knobs for the space animation pipeline.

This package is intentionally board-agnostic: it does not own a per-thread
"active board" or workspace path. The web layer (``app/jobs/``) computes the
board-rooted proposal directory and hands it to ``ops.animate_space``.

Defaults follow ``tech-spec/space-animations/spec.md`` §G5 (target ~3s @ 30 fps,
3 candidates per request, GIF as the default encoding).
"""

from __future__ import annotations

import os

DEFAULT_CANDIDATES = 3
DEFAULT_FPS = 30
DEFAULT_DURATION_MS = 3000
DEFAULT_ENCODING = "gif"
DEFAULT_LOOP_STRATEGY = "crossfade"

ALLOWED_ENCODINGS = ("gif", "apng")
ALLOWED_LOOP_STRATEGIES = ("seamless", "crossfade", "pingpong", "dissolve")


def candidates() -> int:
    """Number of candidate loops produced per animate request."""
    raw = os.environ.get("SPACE_ANIMATIONS_CANDIDATES", str(DEFAULT_CANDIDATES))
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_CANDIDATES
    return max(1, n)


def target_fps() -> int:
    raw = os.environ.get("SPACE_ANIMATIONS_FPS", str(DEFAULT_FPS))
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_FPS
    return max(1, n)


def target_duration_ms() -> int:
    raw = os.environ.get("SPACE_ANIMATIONS_DURATION_MS", str(DEFAULT_DURATION_MS))
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_DURATION_MS
    return max(100, n)


def default_encoding() -> str:
    """Output container: ``gif`` or ``apng``. Anything else falls back to GIF."""
    raw = os.environ.get("SPACE_ANIMATIONS_ENCODING", DEFAULT_ENCODING).strip().lower()
    if raw not in ALLOWED_ENCODINGS:
        return DEFAULT_ENCODING
    return raw


def default_loop_strategy() -> str:
    raw = os.environ.get("SPACE_ANIMATIONS_LOOP", DEFAULT_LOOP_STRATEGY).strip().lower()
    if raw not in ALLOWED_LOOP_STRATEGIES:
        return DEFAULT_LOOP_STRATEGY
    return raw


def provider_name() -> str:
    """Which I2V provider to use.

    Default ``sora`` — calls the OpenAI Sora 2 video API with the
    per-user OpenAI key (see ``providers/sora.py``). Produces real
    image-to-video output but is materially slower (minutes per job)
    and more expensive (per-second billing) than the gpt-image-2
    fallback.

    Other accepted values:

      * ``sora-2-pro``  — higher fidelity Sora variant (~3× cost).
      * ``openai`` / ``gpt-image-2`` — single edit + crossfade morph,
        cheap and fast but limited to crossfade-style motion.
      * ``mock`` — offline; used by the test suite.
    """
    return os.environ.get("SPACE_ANIMATIONS_PROVIDER", "sora").strip().lower() or "sora"

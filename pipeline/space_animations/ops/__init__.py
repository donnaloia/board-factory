"""Atomic operations the web app drives.

Exposes:

- :func:`animate_space.animate_space` — produce N candidate loops + manifest
- :class:`progress.ProgressSink` / :class:`progress.NoopSink`
- :class:`animate_space.AnimateSpec` / :class:`animate_space.AnimateResult`
"""

from .animate_space import (
    AnimateResult,
    AnimateSpec,
    CandidateRecord,
    animate_space,
)
from .progress import NoopSink, ProgressSink

__all__ = [
    "AnimateResult",
    "AnimateSpec",
    "CandidateRecord",
    "animate_space",
    "NoopSink",
    "ProgressSink",
]

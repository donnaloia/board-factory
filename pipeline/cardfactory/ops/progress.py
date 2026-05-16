"""ProgressSink — isolated copy of the boardfactory progress helper.

Keeps ``cardfactory`` self-contained (no cross-pipeline imports).
"""

from __future__ import annotations

from typing import Protocol


class ProgressSink(Protocol):
    """Consumer of pipeline progress events."""

    def emit(self, step: str, detail: str = "", *, pct: float | None = None) -> None:
        """Record a progress event.

        ``step``   — short name of the pipeline step (e.g. ``"chrome_gen"``).
        ``detail`` — human-readable note (e.g. ``"candidate 1/3"``).
        ``pct``    — optional 0..100 completion percentage.
        """
        ...

"""Framework-agnostic progress sink for pipeline operations.

Every long-running pipeline op takes a `ProgressSink` so callers decide
how progress surfaces. The web app supplies a `JobProgressSink` that maps
events onto a `Job`'s log + progress fields. Tests use `NoopSink`.

Three calls is the entire vocabulary:

- `start(label, total)`  — beginning of a unit of work with a known item count
- `step(label, advance)` — one item finished; advance the bar by `advance`
- `log(msg)`             — free-form line, bypasses the bar (errors, notes)

Deliberately tiny so it's hard to overfit to one UI shape. Anything more
expressive (per-step ETAs, nested phases, etc.) would lock the pipeline
into the web app's specific job model.
"""

from __future__ import annotations

from typing import Protocol


class ProgressSink(Protocol):
    def start(self, label: str, total: int) -> None: ...
    def step(self, label: str, advance: int = 1) -> None: ...
    def log(self, msg: str) -> None: ...


class NoopSink:
    """Drops all progress events. Useful for tests and one-off scripts."""

    def start(self, label: str, total: int) -> None:
        return

    def step(self, label: str, advance: int = 1) -> None:
        return

    def log(self, msg: str) -> None:
        return

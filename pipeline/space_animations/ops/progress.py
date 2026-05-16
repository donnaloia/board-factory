"""Framework-agnostic progress sink.

Duplicated from ``boardfactory.ops.progress`` per the no-cross-pipeline-imports
rule (``.cursorrules`` "Pipeline isolation"). Tiny on purpose so the contract
between pipeline and any caller stays trivial.
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

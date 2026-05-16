"""ProgressSink protocol for the tokenfactory pipeline (isolated copy)."""

from __future__ import annotations

from typing import Any, Protocol


class ProgressSink(Protocol):
    def emit(self, event: str, data: Any = None) -> None: ...

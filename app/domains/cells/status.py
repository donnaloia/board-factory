"""Per-cell asset readiness — shared by routes, SVG, and JSON payloads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CellStatus:
    """Per-asset approval status used to color tiles, SVG, and side-panel UI."""

    asset_id: str
    category: str  # "spaces" | "panels" | "centerpiece"
    candidates: int
    approved: bool
    approved_url: str | None  # /asset/... when approved, else None

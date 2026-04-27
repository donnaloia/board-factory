"""Pydantic schema for the board catalog YAML file.

A catalog declares the entire structure of one board: where the board spaces are,
what the feature panels look like, and how the centerpiece is positioned. The
pipeline reads this file once and uses it for every subsequent step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


# ────────────────────────── style + centerpiece ──────────────────────────


class StyleSpec(BaseModel):
    """Project-wide style controls applied to every generation."""

    reference_image: str = Field(
        ..., description="Path (relative to repo root) to your mockup PNG."
    )
    palette_size: int = Field(
        24, ge=4, le=64, description="Number of colors to extract from the reference."
    )
    prompt: str = Field(
        ..., description="Style brief prepended to every generation prompt."
    )


class CenterpieceSpec(BaseModel):
    bbox: tuple[int, int, int, int] = Field(
        ..., description="[x1, y1, x2, y2] of the centerpiece region in the mockup."
    )
    target_size: tuple[int, int] = Field(
        ..., description="[width, height] of the final centerpiece PNG, in true pixels."
    )
    prompt: str = Field("", description="Optional extra prompt for the centerpiece.")
    needs_active: bool = False
    active_kind: Literal["glow", "pulse", "flicker", "none"] = "none"


# ────────────────────────── board spaces ──────────────────────────


class BoardSpaceRow(BaseModel):
    """One linear group of board spaces (e.g. the bottom edge)."""

    count: int = Field(..., ge=1)
    start: tuple[int, int] = Field(..., description="[x, y] of the first space.")
    spacing: int = Field(..., ge=1, description="Pixel distance between successive spaces.")
    axis: Literal["x", "y"] = "x"


class BoardSpaceDesign(BaseModel):
    """One unique board space design that may be repeated at multiple positions."""

    id: str
    prompt: str
    positions: list[str] = Field(
        ..., description="References into the layout, e.g. 'bottom_row.0' or 'left_col.5'."
    )


class BoardSpacesSpec(BaseModel):
    size: tuple[int, int] = Field(..., description="Pixel size of each board space.")
    layout: dict[str, BoardSpaceRow]
    designs: list[BoardSpaceDesign]

    def resolve_position(self, ref: str) -> tuple[int, int]:
        """Resolve a 'row_name.index' reference to absolute mockup pixel coords."""
        try:
            row_name, idx_str = ref.split(".")
            idx = int(idx_str)
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid position reference {ref!r}: expected 'row.index'") from e
        if row_name not in self.layout:
            raise ValueError(f"Unknown row {row_name!r} in position reference {ref!r}")
        row = self.layout[row_name]
        if not 0 <= idx < row.count:
            raise ValueError(
                f"Index {idx} out of range for row {row_name!r} (count={row.count})"
            )
        if row.axis == "x":
            return (row.start[0] + idx * row.spacing, row.start[1])
        return (row.start[0], row.start[1] + idx * row.spacing)


class BoardSpaceLayout(BoardSpacesSpec):
    """Alias kept for export compatibility."""


# ────────────────────────── feature panels ──────────────────────────


class FeaturePanelSpec(BaseModel):
    id: str
    bbox: tuple[int, int, int, int] = Field(
        ..., description="[x1, y1, x2, y2] of the panel region in the mockup."
    )
    target_size: tuple[int, int]
    prompt: str
    needs_active: bool = False
    active_kind: Literal["glow", "pulse", "flicker", "none"] = "none"


class FeaturePanelsSpec(BaseModel):
    panels: list[FeaturePanelSpec]


# ────────────────────────── catalog root ──────────────────────────


class Catalog(BaseModel):
    project: str
    style: StyleSpec
    board_size: tuple[int, int] = Field(..., description="[width, height] of your mockup PNG.")
    centerpiece: CenterpieceSpec
    board_spaces: BoardSpacesSpec
    feature_panels: FeaturePanelsSpec

    @model_validator(mode="after")
    def _validate_positions(self) -> "Catalog":
        for design in self.board_spaces.designs:
            for ref in design.positions:
                self.board_spaces.resolve_position(ref)
        return self

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def all_space_designs(self) -> list[BoardSpaceDesign]:
        return self.board_spaces.designs

    def all_panels(self) -> list[FeaturePanelSpec]:
        return self.feature_panels.panels

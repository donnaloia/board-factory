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
    """One linear group of board spaces (e.g. the bottom edge).

    `size` is per-row so different rows (corners vs sides, top/bottom vs left/right)
    can carry different tile dimensions on the same board.
    """

    count: int = Field(..., ge=1)
    start: tuple[int, int] = Field(..., description="[x, y] of the first space.")
    spacing: int = Field(0, ge=0, description="Pixel distance between successive spaces. Defaults to size along the axis.")
    axis: Literal["x", "y"] = "x"
    size: tuple[int, int] = Field(..., description="[width, height] of every tile in this row.")

    @model_validator(mode="after")
    def _default_spacing(self) -> "BoardSpaceRow":
        # Default spacing to the tile dimension along the row's axis (tiles touch).
        if self.spacing == 0:
            self.spacing = self.size[0] if self.axis == "x" else self.size[1]
        return self


class BoardSpaceDesign(BaseModel):
    """One unique board space design that may be repeated at multiple positions.

    All positions referenced by a single design must come from rows of identical
    size — otherwise we'd be generating one image and stretching it to two
    different aspect ratios. The schema validator enforces this.
    """

    id: str
    prompt: str
    positions: list[str] = Field(
        ..., description="References into the layout, e.g. 'bottom_row.0' or 'left_col.5'."
    )


class BoardSpacesSpec(BaseModel):
    layout: dict[str, BoardSpaceRow]
    designs: list[BoardSpaceDesign]

    def resolve_position(self, ref: str) -> tuple[int, int, int, int]:
        """Resolve a 'row_name.index' reference to (x, y, w, h) in mockup pixels."""
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
            x, y = row.start[0] + idx * row.spacing, row.start[1]
        else:
            x, y = row.start[0], row.start[1] + idx * row.spacing
        return (x, y, row.size[0], row.size[1])

    def design_size(self, design: "BoardSpaceDesign") -> tuple[int, int]:
        """Return the (w, h) shared by every position in this design.

        Raises if positions reference rows of inconsistent size.
        """
        sizes = {self.resolve_position(ref)[2:] for ref in design.positions}
        if len(sizes) != 1:
            raise ValueError(
                f"Design {design.id!r} references positions with inconsistent sizes: {sizes}. "
                f"Move one or more positions to a different design."
            )
        return next(iter(sizes))


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


# ────────────────────────── frame ──────────────────────────


class FrameSpec(BaseModel):
    """House-frame system controls.

    The actual 9-slice sprites live on disk at workspace/frames/house/. This
    block just records whether the system is active for this board and where
    the current frame originated (for display only — the source-of-truth is
    workspace/frames/house/frame.json).
    """

    enabled: bool = Field(
        False,
        description="When true, every functional panel composites the house frame on top of its interior.",
    )
    apply_to_panels: bool = Field(
        True,
        description="If enabled, apply the house frame to functional panels.",
    )
    apply_to_spaces: bool = Field(
        False,
        description="If enabled, apply the house frame to perimeter spaces too. Off by default.",
    )


# ────────────────────────── catalog root ──────────────────────────


class Catalog(BaseModel):
    project: str
    style: StyleSpec
    board_size: tuple[int, int] = Field(..., description="[width, height] of the native board canvas.")
    centerpiece: CenterpieceSpec
    board_spaces: BoardSpacesSpec
    feature_panels: FeaturePanelsSpec
    frame: FrameSpec = Field(default_factory=FrameSpec)

    @model_validator(mode="after")
    def _validate_positions(self) -> "Catalog":
        for design in self.board_spaces.designs:
            for ref in design.positions:
                self.board_spaces.resolve_position(ref)
            self.board_spaces.design_size(design)
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

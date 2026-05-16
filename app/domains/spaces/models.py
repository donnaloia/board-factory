"""Spaces domain — ORM tables: ``cells``, ``frame_instances``.

The space-animations slice (``cells.live_animation_id`` -> ``space_animations``)
lives in :mod:`domains.spaces.animations.models`. We import it at the bottom
of this module so any caller that loads ``CellRecord`` automatically pulls
``SpaceAnimationRecord`` into ``Base.metadata`` — required so the FK target
exists when ``Base.metadata.create_all`` runs on a fresh DB.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


class CellRecord(Base):
    """One painted region on a board: a space, a feature panel, or the centerpiece.

    All three were originally three different shapes — ``body_json``-nested
    designs, ``body_json``-nested panels, and ``board_games.cp_*`` columns.
    Relational consolidation moved perimeter designs, panels, and centerpiece
    here so that "all generation targets
    on this board" is a single ``SELECT * FROM cells WHERE board_uuid = ?``,
    and ``asset_versions.cell_id`` can FK directly to the cell that produced
    each PNG.

    Discriminator: ``kind ∈ {perimeter, functional, centerpiece}``. The DB-level
    CHECK constraint enforces that:

      * perimeter rows have ``space_kind`` + ``positions_json`` and no bbox/target_size
        (their bbox is computed at runtime from
        ``board_games.body_json.board_spaces.layout`` + ``positions``);
      * functional (UI) cells and the centerpiece have full bbox + target_size and no
        ``space_kind`` / ``positions_json``;
      * exactly one centerpiece per board (UNIQUE on
        ``(board_uuid, kind, slug)``).
    """

    __tablename__ = "cells"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    board_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("board_games.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    position_index: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    needs_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="none")

    # Space-only.
    space_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    positions_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Panel + centerpiece.
    bbox_x1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_y1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_x2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_y2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Which ``asset_versions`` row was last promoted to ``workspace/live/…``
    #: for this cell — canonical source for sidebar ``active_prompt`` metadata.
    live_asset_version_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("asset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Which ``space_animations`` row is currently the live looping clip for
    #: this cell, if any. Mirrors ``live_asset_version_id`` for static art.
    #: Only ``kind = 'functional'`` cells can hold a live animation in the
    #: MVP (see ``app/domains/spaces/animations/services.assert_can_animate``).
    live_animation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("space_animations.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Perimeter-design row only: optional ``cells.id`` of a ``kind=functional`` cell to
    #: associate for land → UI / animation (see ``docs/project-export-spec.md`` §10).
    triggers_functional_cell_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("cells.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        sa.UniqueConstraint("board_uuid", "kind", "slug", name="uq_cells_board_kind_slug"),
        Index("ix_cells_board_kind", "board_uuid", "kind"),
        Index("ix_cells_live_asset_version_id", "live_asset_version_id"),
        Index("ix_cells_live_animation_id", "live_animation_id"),
        Index("ix_cells_triggers_functional_cell_id", "triggers_functional_cell_id"),
        sa.CheckConstraint(
            "kind IN ('perimeter','functional','centerpiece')",
            name="ck_cells_kind_enum",
        ),
        sa.CheckConstraint(
            "active_kind IN ('glow','pulse','flicker','none')",
            name="ck_cells_active_kind_enum",
        ),
        sa.CheckConstraint(
            "space_kind IS NULL OR space_kind IN ('standard','event')",
            name="ck_cells_space_kind_enum",
        ),
        sa.CheckConstraint(
            """
            (kind = 'perimeter'
                AND space_kind IS NOT NULL
                AND positions_json IS NOT NULL
                AND bbox_x1 IS NULL AND bbox_y1 IS NULL
                AND bbox_x2 IS NULL AND bbox_y2 IS NULL
                AND target_w IS NULL AND target_h IS NULL)
         OR (kind IN ('functional','centerpiece')
                AND space_kind IS NULL
                AND positions_json IS NULL
                AND bbox_x1 IS NOT NULL AND bbox_y1 IS NOT NULL
                AND bbox_x2 IS NOT NULL AND bbox_y2 IS NOT NULL
                AND target_w IS NOT NULL AND target_h IS NOT NULL)
            """,
            name="ck_cells_shape_by_kind",
        ),
    )


class FrameInstanceRecord(Base):
    """One adopted house frame per board.

    Mirrors the on-disk ``workspace/frames/house/frame.json`` so the
    Atelier can list frames across boards and so the Approach D batch
    regen job has a stable id to attach progress to. Persisted by
    ``app/domains/spaces/frames_repository.py``; the on-disk pack
    (eight slice PNGs + hole/rim masks) remains the source of truth for
    the actual rim pixels.

    Exactly one row per board can have ``active=true`` — the partial
    unique index enforces that without forcing every other row to NULL
    out. Older / replaced instances stay around with ``active=false``
    for provenance-style queries (e.g. "what was the frame before this
    one?").
    """

    __tablename__ = "frame_instances"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    board_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("board_games.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Geometry.
    ring_px: Mapped[int] = mapped_column(Integer, nullable=False)
    source_w: Mapped[int] = mapped_column(Integer, nullable=False)
    source_h: Mapped[int] = mapped_column(Integer, nullable=False)

    # Provenance.
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_cell_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("cells.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_asset_version_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("asset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_frame_instances_board", "board_uuid"),
        Index(
            "uq_frame_instances_one_active_per_board",
            "board_uuid",
            unique=True,
            postgresql_where=sa.text("active = true"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('functional','mockup','upload')",
            name="ck_frame_instances_source_kind",
        ),
        sa.CheckConstraint(
            "ring_px >= 1 AND source_w > 0 AND source_h > 0",
            name="ck_frame_instances_geometry",
        ),
    )


# Register the space-animations sibling table in ``Base.metadata`` whenever
# ``CellRecord`` is loaded. ``CellRecord.live_animation_id`` is a FK to
# ``space_animations.id``; without this import the FK target table would be
# absent from metadata and ``create_all`` would fail to define the
# constraint. Placed at the bottom to avoid any chance of a circular import
# (the animations model only references string FK names, never CellRecord).
import domains.spaces.animations.models  # noqa: E402, F401
import domains.spaces.assets.models  # noqa: E402, F401

"""ORM mapping for ``space_animations`` (one row per committed live animation)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


class SpaceAnimationRecord(Base):
    """A live (committed) looping animation attached to one functional cell.

    Mirrors how ``asset_versions`` records committed static art: one row per
    promotion. Unselected proposal candidates live only on disk under
    ``workspace/animations/<cell_id>/_proposals/<job_id>/`` and are NOT
    indexed here — that's the deliberate "frame proposals" pattern from the
    plan, chosen to avoid filling Postgres with discarded large clips.

    The cell's current live animation is denormalized onto
    ``cells.live_animation_id`` so the side-panel payload can fetch it in
    one query, parallel to ``cells.live_asset_version_id`` for static art.
    """

    __tablename__ = "space_animations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("board_games.id", ondelete="CASCADE"),
        nullable=False,
    )
    cell_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("cells.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_asset_version_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("asset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    rel_path: Mapped[str] = mapped_column(String(512), nullable=False)
    basename: Mapped[str] = mapped_column(String(512), nullable=False)
    encoding: Mapped[str] = mapped_column(String(8), nullable=False)
    fps: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    loop_strategy: Mapped[str] = mapped_column(String(16), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_manifest_rel_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    proposal_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_space_animations_cell_id", "cell_id"),
        Index("ix_space_animations_board_cell", "board_uuid", "cell_id"),
        Index(
            "ix_space_animations_board_relpath",
            "board_uuid",
            "rel_path",
            unique=True,
        ),
        sa.CheckConstraint(
            "encoding IN ('gif','apng')",
            name="ck_space_animations_encoding",
        ),
        sa.CheckConstraint(
            "loop_strategy IN ('seamless','crossfade','pingpong','dissolve')",
            name="ck_space_animations_loop_strategy",
        ),
        sa.CheckConstraint(
            "fps > 0 AND duration_ms > 0 AND frame_count > 0",
            name="ck_space_animations_positive_params",
        ),
    )

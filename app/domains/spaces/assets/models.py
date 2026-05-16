"""Assets domain — ORM table: ``asset_versions``."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


class AssetVersionRecord(Base):
    """One row per history PNG (Phase 3 index + Phase 6 content hash)."""

    __tablename__ = "asset_versions"

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
    # ``category`` + ``asset_id`` mirror ``cells.kind`` + ``cells.slug`` in
    # plural form ("spaces" / "panels" / "centerpiece"). Kept for the
    # filesystem layout (``workspace/history/<category>/<asset_id>/...``)
    # and existing readers; new code should join via ``cell_id``.
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(256), nullable=False)
    basename: Mapped[str] = mapped_column(String(512), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_asset_versions_board_cell", "board_uuid", "category", "asset_id"),
        Index("ix_asset_versions_board_relpath", "board_uuid", "rel_path", unique=True),
        Index("ix_asset_versions_cell_id", "cell_id"),
    )

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.models.base import Base


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon_glyph: Mapped[str] = mapped_column(String(8), nullable=False)
    icon_color: Mapped[str] = mapped_column(String(16), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_login_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    secrets: Mapped[list["UserSecretRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    browser_sessions: Mapped[list["BrowserSessionRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSecretRecord(Base):
    __tablename__ = "user_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["UserRecord"] = relationship(back_populates="secrets")

    __table_args__ = (Index("ix_user_secrets_user_kind", "user_id", "kind", unique=True),)


class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"

    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user: Mapped["UserRecord"] = relationship(back_populates="browser_sessions")


class OwnedBoardRecord(Base):
    """Maps a board directory (slug) to exactly one owning user.

    ``user_id`` is required at the application layer and is ``NOT NULL`` in the database.
    """

    __tablename__ = "owned_boards"

    board_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class JobRunRecord(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eta_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    __table_args__ = (Index("ix_job_runs_ended_at", "ended_at"),)


class CostEntryRecord(Base):
    __tablename__ = "cost_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    op: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    usd: Mapped[float] = mapped_column(Float, nullable=False)


class BoardCatalogRecord(Base):
    """Legacy mirror of the full catalog JSON (kept in sync for transitional code)."""

    __tablename__ = "board_catalogs"

    board_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BoardGameRecord(Base):
    """One row per board: global board spec (parent for normalized children)."""

    __tablename__ = "board_games"

    board_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project: Mapped[str] = mapped_column(String(512), nullable=False)
    board_size_w: Mapped[int] = mapped_column(Integer, nullable=False)
    board_size_h: Mapped[int] = mapped_column(Integer, nullable=False)
    style_reference_image: Mapped[str] = mapped_column(String(512), nullable=False)
    style_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    cp_bbox_x1: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_bbox_y1: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_bbox_x2: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_bbox_y2: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_target_w: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_target_h: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    cp_needs_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cp_active_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    generation_json: Mapped[str] = mapped_column(Text, nullable=False)
    frame_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    palette_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    palette_gpl_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_lock_updated_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class BoardSpaceLayoutRowRecord(Base):
    """One row of the ``board_spaces.layout`` map (e.g. top_row, bottom_row)."""

    __tablename__ = "board_space_layout_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("board_games.board_id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_key: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_x: Mapped[int] = mapped_column(Integer, nullable=False)
    start_y: Mapped[int] = mapped_column(Integer, nullable=False)
    spacing: Mapped[int] = mapped_column(Integer, nullable=False)
    axis: Mapped[str] = mapped_column(String(1), nullable=False)
    size_w: Mapped[int] = mapped_column(Integer, nullable=False)
    size_h: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_board_space_layout_board_row", "board_id", "row_key", unique=True),)


class BoardSpaceDesignRecord(Base):
    """One space design (id + prompt + position refs) for a board."""

    __tablename__ = "board_space_designs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("board_games.board_id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    design_id: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    space_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    positions_json: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_board_space_designs_board_design", "board_id", "design_id", unique=True),)


class BoardFeaturePanelRecord(Base):
    """One functional panel region for a board."""

    __tablename__ = "board_feature_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("board_games.board_id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    panel_id: Mapped[str] = mapped_column(String(256), nullable=False)
    bbox_x1: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y1: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_x2: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y2: Mapped[int] = mapped_column(Integer, nullable=False)
    target_w: Mapped[int] = mapped_column(Integer, nullable=False)
    target_h: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    needs_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="none")

    __table_args__ = (Index("ix_board_feature_panels_board_panel", "board_id", "panel_id", unique=True),)


class AssetVersionRecord(Base):
    """One row per history PNG (Phase 3 index + Phase 6 content hash)."""

    __tablename__ = "asset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(256), nullable=False)
    basename: Mapped[str] = mapped_column(String(512), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_asset_versions_board_cell", "board_id", "category", "asset_id"),
        Index("ix_asset_versions_board_relpath", "board_id", "rel_path", unique=True),
    )


class AssetLiveRecord(Base):
    """DB-backed pointer to the on-disk image that is ``live`` for one cell."""

    __tablename__ = "asset_live"

    board_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("board_games.board_id", ondelete="CASCADE"),
        primary_key=True,
    )
    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    live_rel_path: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

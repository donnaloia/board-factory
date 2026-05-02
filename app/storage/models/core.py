from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Float, Index, Integer, String, Text
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


class BoardGameRecord(Base):
    """One row per board.

    The catalog spec (project, board_size, style, centerpiece, board_spaces,
    feature_panels, frame, generation) is a Pydantic-validated JSON blob in
    ``body_json``. Style-lock palette state has its own columns because the
    palette has a separate writer that materializes it to disk on job start.
    """

    __tablename__ = "board_games"

    board_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    palette_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    palette_gpl_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_lock_updated_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


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



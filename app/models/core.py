from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, ForeignKey, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
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
    """Maps a board UUID (PK of ``board_games``) to exactly one owning user.

    ``path_slug`` is the URL segment under ``/users/<name>/board-games/<slug>/``.
    """

    __tablename__ = "owned_boards"

    board_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("board_games.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    path_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    list_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "path_slug", name="uq_owned_boards_user_path_slug"),
    )


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

    Fixed-shape catalog fields live as typed columns. Per-cell data
    (board spaces, feature panels, centerpiece) lives in the ``cells``
    table — see :class:`CellRecord`. ``body_json`` now holds only the
    perimeter ``board_spaces.layout`` map (geometry shared by spaces).

    The Pydantic ``Catalog`` validator is the read/write façade — see
    ``services.board_definition._row_to_catalog_dict``, which joins
    ``board_games`` + ``cells`` back into the legacy nested shape.

    ``palette_*`` and ``style_lock_updated_ms`` are written by
    ``boards.palette`` after each style-lock job; they are not part
    of the catalog payload.
    """

    __tablename__ = "board_games"

    board_uuid: Mapped[str] = mapped_column("id", String(36), primary_key=True)

    project: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    board_size_w: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    board_size_h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    style_reference_image: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    palette_size: Mapped[int] = mapped_column(Integer, nullable=False, default=36)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    openai_model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-image-2")
    openai_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    pixellab_model: Mapped[str] = mapped_column(String(64), nullable=False, default="pixflux_sharp")
    generation_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    frame_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frame_apply_to_panels: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    frame_apply_to_spaces: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    body_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    palette_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    palette_gpl_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_lock_updated_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class CellRecord(Base):
    """One painted region on a board: a space, a feature panel, or the centerpiece.

    All three were originally three different shapes — ``body_json``-nested
    designs, ``body_json``-nested panels, and ``board_games.cp_*`` columns.
    Migration ``0019`` consolidated them here so that "all generation targets
    on this board" is a single ``SELECT * FROM cells WHERE board_uuid = ?``,
    and ``asset_versions.cell_id`` can FK directly to the cell that produced
    each PNG.

    Discriminator: ``kind ∈ {space, panel, centerpiece}``. The DB-level CHECK
    constraint enforces that:

      * spaces have ``space_kind`` + ``positions_json`` and no bbox/target_size
        (their bbox is computed at runtime from
        ``board_games.body_json.board_spaces.layout`` + ``positions``);
      * panels and centerpieces have full bbox + target_size and no
        ``space_kind`` / ``positions_json``;
      * exactly one centerpiece per board (UNIQUE on
        ``(board_uuid, kind, slug)``).
    """

    __tablename__ = "cells"

    id: Mapped[str] = mapped_column(
        sa.dialects.postgresql.UUID(as_uuid=False),
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

    __table_args__ = (
        sa.UniqueConstraint("board_uuid", "kind", "slug", name="uq_cells_board_kind_slug"),
        Index("ix_cells_board_kind", "board_uuid", "kind"),
    )


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
        sa.dialects.postgresql.UUID(as_uuid=False),
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



"""Boards domain — ORM tables: ``owned_boards``, ``board_games``."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


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


class BoardGameRecord(Base):
    """One row per board.

    Fixed-shape catalog fields live as typed columns. Per-cell data
    (board spaces, feature panels, centerpiece) lives in the ``cells``
    table — see :class:`cells.models.CellRecord`. ``body_json`` now holds only the
    perimeter ``board_spaces.layout`` map (geometry shared by spaces).

    The Pydantic ``Catalog`` validator is the read/write façade — see
    ``boards.services._row_to_catalog_dict``, which joins
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

"""Tokens domain — ORM table: ``token_records``."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from infrastructure.orm import Base


class TokenRecord(Base):
    """One character token owned by a user.

    Tokens are a top-level domain (``Token Factory``); a board is *optional*
    palette source via ``linked_board_id``.

    Design lock = ``design_locked`` is True + ``references/canonical.png``
    exists on disk + ``design_lock.json`` written.

    ``live_run_id`` points at the sub-directory inside
    ``data/tokens/<id>/animations/history/<run_id>/`` that holds the current
    promoted animation pack. NULL until the first pack is published.
    """

    __tablename__ = "token_records"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linked_board_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("board_games.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: URL segment under ``/users/<name>/token-factory/<path_slug>/``.
    path_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Legacy short label — also used in ``design_lock.json`` and prompts.
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    #: walk | float | fly
    locomotion_profile: Mapped[str] = mapped_column(
        String(8), nullable=False, default="walk"
    )
    #: flip_x | four_way
    facing_policy: Mapped[str] = mapped_column(
        String(8), nullable=False, default="flip_x"
    )

    canvas_w: Mapped[int] = mapped_column(Integer, nullable=False, default=96)
    canvas_h: Mapped[int] = mapped_column(Integer, nullable=False, default=128)
    frame_fps: Mapped[int] = mapped_column(Integer, nullable=False, default=12)

    design_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    #: run_id of the current live animation pack (NULL before first publish)
    live_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "owner_user_id", "path_slug", name="uq_token_records_user_path_slug"
        ),
        sa.CheckConstraint(
            "locomotion_profile IN ('walk','float','fly')",
            name="ck_token_records_locomotion",
        ),
        sa.CheckConstraint(
            "facing_policy IN ('flip_x','four_way')",
            name="ck_token_records_facing",
        ),
    )

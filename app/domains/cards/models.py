"""Cards domain — ORM tables: ``card_decks``, ``card_frame_candidates``, ``card_slot_records``."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


class CardDeckRecord(Base):
    """One Card Factory project — links to a source board and tracks pipeline state.

    ``committed_frame_id`` is a nullable FK to ``card_frame_candidates.id`` using
    ``use_alter=True`` to defer the constraint until after both tables exist
    (resolves the circular reference between decks and candidates).
    """

    __tablename__ = "card_decks"

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
    path_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    project_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    #: Lifecycle gate: draft → frame_pending → card_pending → complete
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    slot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    layout_template_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="portrait-two-band-v1"
    )

    #: Set when user commits one frame candidate (deferred FK — see use_alter).
    committed_frame_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "card_frame_candidates.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_card_decks_committed_frame_id",
        ),
        nullable=True,
    )

    #: Style + generation parameters copied from the linked board at link time.
    style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    palette_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    openai_model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-image-2")
    openai_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="low")

    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("owner_user_id", "path_slug", name="uq_card_decks_user_path_slug"),
        sa.CheckConstraint(
            "status IN ('draft','frame_pending','card_pending','complete')",
            name="ck_card_decks_status",
        ),
    )


class CardFrameCandidateRecord(Base):
    """One of the three generated chrome candidates at the frame gate.

    Rows are written by ``generate_frames_job`` after each successful
    provider call. The user picks one and ``card_decks.committed_frame_id``
    is pointed at that row's ``id``.
    """

    __tablename__ = "card_frame_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("card_decks.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Forward-slash relative path under the deck workspace.
    rel_path: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Pixel-space inner hull computed at gen time: {x, y, w, h}.
    inner_rect_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: SHA-256 of the M_chrome_paint mask bytes used during generation.
    m_chrome_paint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        sa.Index("ix_card_frame_candidates_deck_job", "deck_id", "job_id"),
        sa.CheckConstraint(
            "candidate_index >= 0 AND candidate_index <= 2",
            name="ck_card_frame_candidates_index",
        ),
    )


class CardSlotRecord(Base):
    """One card position within a deck.

    ``slot_index`` is 0-based; ``slot_count`` on the parent deck sets how many
    rows exist. Prompt fields are written by ``derive_prompts_job`` and may be
    overridden by the user before regeneration.
    """

    __tablename__ = "card_slot_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("card_decks.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    illustration_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stat_lines_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Whether the prompt came from the agent or was manually edited.
    prompt_source: Mapped[str] = mapped_column(String(8), nullable=False, default="agent")

    #: Path to the final composited PNG (live card), relative to deck workspace.
    live_rel_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    #: Which frame candidate was committed when this card was last generated.
    live_frame_commit_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("card_frame_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("deck_id", "slot_index", name="uq_card_slot_deck_index"),
        sa.CheckConstraint(
            "prompt_source IN ('agent','user')",
            name="ck_card_slot_prompt_source",
        ),
        sa.Index("ix_card_slot_records_deck_id", "deck_id"),
    )

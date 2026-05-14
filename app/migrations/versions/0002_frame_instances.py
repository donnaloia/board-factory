"""Add frame_instances table for the Frame Atelier.

Revision ID: 0002_frame_instances
Revises: 0001_full_schema
Create Date: 2026-05-06

Backed by ``app/domains/spaces/models.py``'s ``FrameInstanceRecord``. The
on-disk pack at ``workspace/frames/house/`` remains the source of truth
for the actual nine-slice + masks; this table stores provenance and the
"one active frame per board" invariant for the Atelier UI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_frame_instances"
down_revision: Union[str, None] = "0001_full_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "frame_instances",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "board_uuid",
            sa.String(36),
            sa.ForeignKey("board_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ring_px", sa.Integer(), nullable=False),
        sa.Column("source_w", sa.Integer(), nullable=False),
        sa.Column("source_h", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=True),
        sa.Column(
            "source_cell_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cells.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_asset_version_id",
            sa.Integer(),
            sa.ForeignKey("asset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        sa.Column("candidate_index", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('panel','mockup','upload')",
            name="ck_frame_instances_source_kind",
        ),
        sa.CheckConstraint(
            "ring_px >= 1 AND source_w > 0 AND source_h > 0",
            name="ck_frame_instances_geometry",
        ),
    )
    op.create_index(
        "ix_frame_instances_board",
        "frame_instances",
        ["board_uuid"],
    )
    op.create_index(
        "uq_frame_instances_one_active_per_board",
        "frame_instances",
        ["board_uuid"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_frame_instances_one_active_per_board", table_name="frame_instances"
    )
    op.drop_index("ix_frame_instances_board", table_name="frame_instances")
    op.drop_table("frame_instances")

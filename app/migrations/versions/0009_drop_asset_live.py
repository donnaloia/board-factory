"""Drop the asset_live pointer table.

Revision ID: 0009_drop_asset_live
Revises: 0008_space_kind
Create Date: 2026-05-02

The on-disk ``workspace/live/<category>/<asset_id>.png`` is now treated as
the canonical source of truth for "which image is live for this cell" - it
is tracked in git so a fresh clone reproduces the board grid. The DB
pointer that mirrored the live file is no longer needed.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0009_drop_asset_live"
down_revision: Union[str, None] = "0008_space_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_asset_live_board_id", table_name="asset_live")
    op.drop_table("asset_live")


def downgrade() -> None:
    import sqlalchemy as sa

    op.create_table(
        "asset_live",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=256), nullable=False),
        sa.Column("live_rel_path", sa.String(length=512), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["board_id"], ["board_games.board_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("board_id", "category", "asset_id"),
    )
    op.create_index(
        "ix_asset_live_board_id", "asset_live", ["board_id"], unique=False
    )

"""Per-user board ownership.

Every ``owned_boards`` row requires a non-null ``user_id`` (FK to ``users``).
Boards cannot exist in this table without an owning user.

Revision ID: 0005_owned_boards
Revises: 0004_board_game_relational
Create Date: 2026-05-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_owned_boards"
down_revision: Union[str, None] = "0004_board_game_relational"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "owned_boards",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("board_id"),
    )
    op.create_index("ix_owned_boards_user_id", "owned_boards", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_owned_boards_user_id", table_name="owned_boards")
    op.drop_table("owned_boards")

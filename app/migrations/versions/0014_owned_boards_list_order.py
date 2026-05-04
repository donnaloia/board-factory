"""Add owned_boards.list_order for home-page board list ordering.

Revision ID: 0014_owned_boards_list_order
Revises: 0013_rename_demo_board

Smaller ``list_order`` values appear first; ties fall back to project title
(case-insensitive), then ``board_id``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_owned_boards_list_order"
down_revision: Union[str, None] = "0013_rename_demo_board"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "owned_boards",
        sa.Column("list_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("owned_boards", "list_order")

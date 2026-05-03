"""Drop the legacy board_catalogs JSON-blob mirror.

Revision ID: 0010_drop_board_catalogs
Revises: 0009_drop_asset_live
Create Date: 2026-05-02

The full catalog spec lives in ``board_games`` + child tables. The
``board_catalogs.body_json`` mirror that was kept in sync for transitional
readers no longer has any reader. Drop it.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0010_drop_board_catalogs"
down_revision: Union[str, None] = "0009_drop_asset_live"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("board_catalogs")


def downgrade() -> None:
    import sqlalchemy as sa

    op.create_table(
        "board_catalogs",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("body_json", sa.Text(), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("board_id"),
    )

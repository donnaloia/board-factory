"""Palette columns on board_games + asset_live pointers.

Revision ID: 0006_ws_palette_live (kept ≤32 chars for alembic_version.version_num)
Revises: 0005_owned_boards
Create Date: 2026-05-01

- ``board_games``: optional persisted style-lock palette (JSON + GPL text).
- ``asset_live``: which workspace-relative path is "live" for each cell
  (typically under ``history/``; falls back to ``live/`` during migration).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_ws_palette_live"
down_revision: Union[str, None] = "0005_owned_boards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("board_games", sa.Column("palette_json", sa.Text(), nullable=True))
    op.add_column("board_games", sa.Column("palette_gpl_text", sa.Text(), nullable=True))
    op.add_column("board_games", sa.Column("style_lock_updated_ms", sa.BigInteger(), nullable=True))

    op.create_table(
        "asset_live",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=256), nullable=False),
        sa.Column("live_rel_path", sa.String(length=512), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("board_id", "category", "asset_id"),
    )
    op.create_index("ix_asset_live_board_id", "asset_live", ["board_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_live_board_id", table_name="asset_live")
    op.drop_table("asset_live")
    op.drop_column("board_games", "style_lock_updated_ms")
    op.drop_column("board_games", "palette_gpl_text")
    op.drop_column("board_games", "palette_json")

"""Relational board definition (BoardGame + spaces + panels).

Revision ID: 0004_board_game_relational
Revises: 0003_phase34_catalog_assets
Create Date: 2026-05-01

Normalized storage for the board spec previously held only in ``board_catalogs``
JSON. ``board_catalogs`` remains populated in sync for transitional readers.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_board_game_relational"
down_revision: Union[str, None] = "0003_phase34_catalog_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "board_games",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("project", sa.String(length=512), nullable=False),
        sa.Column("board_size_w", sa.Integer(), nullable=False),
        sa.Column("board_size_h", sa.Integer(), nullable=False),
        sa.Column("style_reference_image", sa.String(length=512), nullable=False),
        sa.Column("style_prompt", sa.Text(), nullable=False),
        sa.Column("cp_bbox_x1", sa.Integer(), nullable=False),
        sa.Column("cp_bbox_y1", sa.Integer(), nullable=False),
        sa.Column("cp_bbox_x2", sa.Integer(), nullable=False),
        sa.Column("cp_bbox_y2", sa.Integer(), nullable=False),
        sa.Column("cp_target_w", sa.Integer(), nullable=False),
        sa.Column("cp_target_h", sa.Integer(), nullable=False),
        sa.Column("cp_prompt", sa.Text(), nullable=False),
        sa.Column("cp_needs_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("cp_active_kind", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("generation_json", sa.Text(), nullable=False),
        sa.Column("frame_json", sa.Text(), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("board_id"),
    )

    op.create_table(
        "board_space_layout_rows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_key", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("start_x", sa.Integer(), nullable=False),
        sa.Column("start_y", sa.Integer(), nullable=False),
        sa.Column("spacing", sa.Integer(), nullable=False),
        sa.Column("axis", sa.String(length=1), nullable=False),
        sa.Column("size_w", sa.Integer(), nullable=False),
        sa.Column("size_h", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_space_layout_board_row",
        "board_space_layout_rows",
        ["board_id", "row_key"],
        unique=True,
    )

    op.create_table(
        "board_space_designs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("design_id", sa.String(length=256), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("positions_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_space_designs_board_design",
        "board_space_designs",
        ["board_id", "design_id"],
        unique=True,
    )

    op.create_table(
        "board_feature_panels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("panel_id", sa.String(length=256), nullable=False),
        sa.Column("bbox_x1", sa.Integer(), nullable=False),
        sa.Column("bbox_y1", sa.Integer(), nullable=False),
        sa.Column("bbox_x2", sa.Integer(), nullable=False),
        sa.Column("bbox_y2", sa.Integer(), nullable=False),
        sa.Column("target_w", sa.Integer(), nullable=False),
        sa.Column("target_h", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("needs_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("active_kind", sa.String(length=16), nullable=False, server_default="none"),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_feature_panels_board_panel",
        "board_feature_panels",
        ["board_id", "panel_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_board_feature_panels_board_panel", table_name="board_feature_panels")
    op.drop_table("board_feature_panels")
    op.drop_index("ix_board_space_designs_board_design", table_name="board_space_designs")
    op.drop_table("board_space_designs")
    op.drop_index("ix_board_space_layout_board_row", table_name="board_space_layout_rows")
    op.drop_table("board_space_layout_rows")
    op.drop_table("board_games")

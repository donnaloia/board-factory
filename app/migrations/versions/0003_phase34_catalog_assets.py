"""Phase 3–4: canonical catalog JSON + indexed asset history rows.

Revision ID: 0003_phase34_catalog_assets
Revises: 0002_phase2_core_tables
Create Date: 2026-05-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_phase34_catalog_assets"
down_revision: Union[str, None] = "0002_phase2_core_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "board_catalogs",
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("body_json", sa.Text(), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("board_id"),
    )

    op.create_table(
        "asset_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=256), nullable=False),
        sa.Column("basename", sa.String(length=512), nullable=False),
        sa.Column("rel_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("ts_ms", sa.BigInteger(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_asset_versions_board_cell",
        "asset_versions",
        ["board_id", "category", "asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_asset_versions_board_relpath",
        "asset_versions",
        ["board_id", "rel_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_asset_versions_board_relpath", table_name="asset_versions")
    op.drop_index("ix_asset_versions_board_cell", table_name="asset_versions")
    op.drop_table("asset_versions")
    op.drop_table("board_catalogs")

"""Add space_kind to board space designs (standard vs event).

Revision ID: 0008_space_kind (≤32 chars for Postgres alembic_version.version_num)
Revises: 0007_seed_dev_admin_user
Create Date: 2026-05-02

Optional per-design role for future prompt / export context. Existing rows
backfill to ``standard``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_space_kind"
down_revision: Union[str, None] = "0007_seed_dev_admin_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "board_space_designs",
        sa.Column(
            "space_kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("board_space_designs", "space_kind")

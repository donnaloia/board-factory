"""Phase 2: users, secrets, browser sessions, job runs, cost entries.

Revision ID: 0002_phase2_core_tables
Revises: 0001_baseline
Create Date: 2026-04-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_phase2_core_tables"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("icon_glyph", sa.String(length=8), nullable=False),
        sa.Column("icon_color", sa.String(length=16), nullable=False),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_login_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "user_secrets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_secrets_user_id"), "user_secrets", ["user_id"], unique=False)
    op.create_index("ix_user_secrets_user_kind", "user_secrets", ["user_id", "kind"], unique=True)

    op.create_table(
        "browser_sessions",
        sa.Column("sid", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sid"),
    )
    op.create_index(op.f("ix_browser_sessions_user_id"), "browser_sessions", ["user_id"], unique=False)

    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("eta_s", sa.Float(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=False),
        sa.Column("cost_actual", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("ended_at", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("log_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_ended_at", "job_runs", ["ended_at"], unique=False)

    op.create_table(
        "cost_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.Column("op", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=True),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("usd", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cost_entries_ts"), "cost_entries", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cost_entries_ts"), table_name="cost_entries")
    op.drop_table("cost_entries")
    op.drop_index("ix_job_runs_ended_at", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index(op.f("ix_browser_sessions_user_id"), table_name="browser_sessions")
    op.drop_table("browser_sessions")
    op.drop_index("ix_user_secrets_user_kind", table_name="user_secrets")
    op.drop_index(op.f("ix_user_secrets_user_id"), table_name="user_secrets")
    op.drop_table("user_secrets")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

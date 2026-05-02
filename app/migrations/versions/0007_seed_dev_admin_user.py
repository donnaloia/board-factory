"""Seed default dev admin when ``users`` is empty.

Revision ID: 0007_seed_dev_admin_user
Revises: 0006_ws_palette_live
Create Date: 2026-05-01

Inserts the historical bootstrap account (same bcrypt hash as the old
``boards/.users.json``) so a fresh ``alembic upgrade head`` yields a login
without maintaining a separate JSON file.

Login: ``admin@admin.com`` / ``boardfactory-dev`` (change after first use).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_seed_dev_admin_user"
down_revision: Union[str, None] = "0006_ws_palette_live"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Stable id + bcrypt hash previously shipped in ``boards/.users.json``.
_DEV_ADMIN_ID = "46c004b7a2a9482398aa262d103cf96e"
_DEV_ADMIN_EMAIL = "admin@admin.com"
_DEV_PASSWORD_HASH = (
    "$2b$12$heJK13dCZiAd838HM8DsL.XHvM0elqeVGuZwmafq7A6lvQEZ7jgOW"
)


def upgrade() -> None:
    conn = op.get_bind()
    n = conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one()
    if int(n) > 0:
        return
    conn.execute(
        sa.text(
            """
            INSERT INTO users (
                id, email, password_hash, display_name,
                icon_glyph, icon_color, created_ms, last_login_ms
            ) VALUES (
                :id, :email, :password_hash, :display_name,
                :icon_glyph, :icon_color, :created_ms, :last_login_ms
            )
            """
        ),
        {
            "id": _DEV_ADMIN_ID,
            "email": _DEV_ADMIN_EMAIL,
            "password_hash": _DEV_PASSWORD_HASH,
            "display_name": "ben",
            "icon_glyph": "✧",
            "icon_color": "#902de1",
            "created_ms": 1777514766934,
            "last_login_ms": 1777600770172,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM users WHERE id = :id AND email = :email"),
        {"id": _DEV_ADMIN_ID, "email": _DEV_ADMIN_EMAIL},
    )

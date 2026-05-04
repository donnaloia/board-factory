"""URL paths: users.username + owned_boards.path_slug.

Revision ID: 0012_user_board_urls
Revises: 0011_body_json

Adds ``users.username`` (unique slug for ``/users/<username>/...``) and
``owned_boards.path_slug`` (unique per owner for ``.../board-games/<slug>/``).
Disk remains ``data/boards/<board_id>/``; URLs map through these columns.
"""

from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_user_board_urls"
down_revision: Union[str, None] = "0011_body_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _slugify(name: str) -> str:
    if not name:
        return "user"
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    return (s or "user")[:64]


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
    op.add_column(
        "owned_boards",
        sa.Column("path_slug", sa.String(length=128), nullable=True),
    )

    users_rows = conn.execute(sa.text("SELECT id, email FROM users")).fetchall()
    seen: set[str] = set()
    for uid, email in users_rows:
        local = (email or "").split("@")[0]
        base = _slugify(local)
        cand = base
        n = 0
        while cand in seen:
            n += 1
            cand = f"{base}-{n}"[:64]
        seen.add(cand)
        conn.execute(
            sa.text("UPDATE users SET username = :u WHERE id = :id"),
            {"u": cand, "id": uid},
        )

    conn.execute(
        sa.text("UPDATE owned_boards SET path_slug = board_id WHERE path_slug IS NULL")
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_users_username", ["username"])

    with op.batch_alter_table("owned_boards", schema=None) as batch_op:
        batch_op.alter_column(
            "path_slug",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_owned_boards_user_path_slug",
            ["user_id", "path_slug"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_owned_boards_user_path_slug", "owned_boards", type_="unique")
    op.drop_column("owned_boards", "path_slug")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")

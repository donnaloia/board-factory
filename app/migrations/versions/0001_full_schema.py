"""Single baseline schema (full ORM metadata).

Revision ID: 0001_full_schema
Revises:
Create Date: 2026-05-02

This replaces the prior multi-step migration chain. **New databases**: run
``alembic upgrade head`` from ``app/`` against an empty Postgres instance.

**Optional dev data:** restore a plain-SQL snapshot from ``db/snapshots/`` (see
``db/snapshots/README.md``) — regenerate that dump after schema changes so its
``alembic_version`` row matches ``0001_full_schema``.

Downgrade drops all application tables (destructive).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_full_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    from infrastructure.orm import Base

    import auth.models  # noqa: F401
    import jobs.models  # noqa: F401
    import assets.models  # noqa: F401
    import domains.boards.models  # noqa: F401
    import domains.cells.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from infrastructure.orm import Base

    import auth.models  # noqa: F401
    import jobs.models  # noqa: F401
    import assets.models  # noqa: F401
    import domains.boards.models  # noqa: F401
    import domains.cells.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind)

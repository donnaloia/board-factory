"""Single baseline schema — full current ORM.

Revision ID: 0001_full_schema
Revises:
Create Date: 2026-05-16

This is the single migration for the repository. It creates the complete
current schema by reflecting all ORM models via ``Base.metadata.create_all``.
There is no migration chain: new databases run ``alembic upgrade head`` once
and they are at head.

See ``postgres-snapshots/README.md`` for restoring an existing dev dataset.
Add a new revision on top of this file when a schema change is needed going
forward.

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
    from infrastructure.orm import Base  # noqa: PLC0415

    import auth.models  # noqa: F401, PLC0415
    import jobs.models  # noqa: F401, PLC0415
    import domains.spaces.assets.models  # noqa: F401, PLC0415
    import domains.boards.models  # noqa: F401, PLC0415
    import domains.spaces.models  # noqa: F401, PLC0415
    import domains.spaces.animations.models  # noqa: F401, PLC0415
    import domains.cards.models  # noqa: F401, PLC0415
    import domains.tokens.models  # noqa: F401, PLC0415

    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from infrastructure.orm import Base  # noqa: PLC0415

    import auth.models  # noqa: F401, PLC0415
    import jobs.models  # noqa: F401, PLC0415
    import domains.spaces.assets.models  # noqa: F401, PLC0415
    import domains.boards.models  # noqa: F401, PLC0415
    import domains.spaces.models  # noqa: F401, PLC0415
    import domains.spaces.animations.models  # noqa: F401, PLC0415
    import domains.cards.models  # noqa: F401, PLC0415
    import domains.tokens.models  # noqa: F401, PLC0415

    bind = op.get_bind()
    Base.metadata.drop_all(bind)

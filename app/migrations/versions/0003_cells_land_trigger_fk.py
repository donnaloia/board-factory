"""cells: nullable FK for perimeter design → functional panel land trigger.

Revision ID: 0003_cells_land_trigger_fk
Revises: 0002_frame_instances
Create Date: 2026-05-09

See ``docs/project-export-spec.md`` §10 — ``triggers_functional_cell_id`` on
``kind = 'space'`` rows points at a ``kind = 'panel'`` row on the same board.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_cells_land_trigger_fk"
down_revision: Union[str, None] = "0002_frame_instances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cells",
        sa.Column(
            "triggers_functional_cell_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_cells_triggers_functional_cell_id",
        "cells",
        "cells",
        ["triggers_functional_cell_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cells_triggers_functional_cell_id",
        "cells",
        ["triggers_functional_cell_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cells_triggers_functional_cell_id", table_name="cells")
    op.drop_constraint("fk_cells_triggers_functional_cell_id", "cells", type_="foreignkey")
    op.drop_column("cells", "triggers_functional_cell_id")

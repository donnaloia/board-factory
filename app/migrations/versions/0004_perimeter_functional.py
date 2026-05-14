"""cells.kind: space→perimeter, panel→functional; frame source_kind: panel→functional.

Revision ID: 0004_perimeter_functional
Revises: 0003_cells_land_trigger_fk
Create Date: 2026-05-14

Rewrites discriminator literals on ``cells`` and ``frame_instances``, then
replaces CHECK constraints to match ``domains.spaces.models``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0004_perimeter_functional"
down_revision: Union[str, None] = "0003_cells_land_trigger_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHAPE_BY_KIND_NEW = """
(kind = 'perimeter'
    AND space_kind IS NOT NULL
    AND positions_json IS NOT NULL
    AND bbox_x1 IS NULL AND bbox_y1 IS NULL
    AND bbox_x2 IS NULL AND bbox_y2 IS NULL
    AND target_w IS NULL AND target_h IS NULL)
 OR (kind IN ('functional','centerpiece')
    AND space_kind IS NULL
    AND positions_json IS NULL
    AND bbox_x1 IS NOT NULL AND bbox_y1 IS NOT NULL
    AND bbox_x2 IS NOT NULL AND bbox_y2 IS NOT NULL
    AND target_w IS NOT NULL AND target_h IS NOT NULL)
"""

_SHAPE_BY_KIND_OLD = """
(kind = 'space'
    AND space_kind IS NOT NULL
    AND positions_json IS NOT NULL
    AND bbox_x1 IS NULL AND bbox_y1 IS NULL
    AND bbox_x2 IS NULL AND bbox_y2 IS NULL
    AND target_w IS NULL AND target_h IS NULL)
 OR (kind IN ('panel','centerpiece')
    AND space_kind IS NULL
    AND positions_json IS NULL
    AND bbox_x1 IS NOT NULL AND bbox_y1 IS NOT NULL
    AND bbox_x2 IS NOT NULL AND bbox_y2 IS NOT NULL
    AND target_w IS NOT NULL AND target_h IS NOT NULL)
"""


def upgrade() -> None:
    op.drop_constraint("ck_cells_kind_enum", "cells", type_="check")
    op.drop_constraint("ck_cells_shape_by_kind", "cells", type_="check")
    op.execute("UPDATE cells SET kind = 'perimeter' WHERE kind = 'space'")
    op.execute("UPDATE cells SET kind = 'functional' WHERE kind = 'panel'")
    op.create_check_constraint(
        "ck_cells_kind_enum",
        "cells",
        "kind IN ('perimeter','functional','centerpiece')",
    )
    op.create_check_constraint(
        "ck_cells_shape_by_kind",
        "cells",
        _SHAPE_BY_KIND_NEW,
    )

    op.drop_constraint(
        "ck_frame_instances_source_kind",
        "frame_instances",
        type_="check",
    )
    op.execute(
        "UPDATE frame_instances SET source_kind = 'functional' "
        "WHERE source_kind = 'panel'"
    )
    op.create_check_constraint(
        "ck_frame_instances_source_kind",
        "frame_instances",
        "source_kind IN ('functional','mockup','upload')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_frame_instances_source_kind",
        "frame_instances",
        type_="check",
    )
    op.execute(
        "UPDATE frame_instances SET source_kind = 'panel' "
        "WHERE source_kind = 'functional'"
    )
    op.create_check_constraint(
        "ck_frame_instances_source_kind",
        "frame_instances",
        "source_kind IN ('panel','mockup','upload')",
    )

    op.drop_constraint("ck_cells_kind_enum", "cells", type_="check")
    op.drop_constraint("ck_cells_shape_by_kind", "cells", type_="check")
    op.execute("UPDATE cells SET kind = 'space' WHERE kind = 'perimeter'")
    op.execute("UPDATE cells SET kind = 'panel' WHERE kind = 'functional'")
    op.create_check_constraint(
        "ck_cells_kind_enum",
        "cells",
        "kind IN ('space','panel','centerpiece')",
    )
    op.create_check_constraint(
        "ck_cells_shape_by_kind",
        "cells",
        _SHAPE_BY_KIND_OLD,
    )

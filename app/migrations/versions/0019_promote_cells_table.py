"""Promote board cells (spaces + panels + centerpiece) to a first-class table.

Revision ID: 0019_promote_cells_table
Revises: 0018_extract_style_centerpiece
Create Date: 2026-05-04

A *cell* is one painted region of a board — a board space (perimeter tile),
a feature panel, or the centerpiece. Until now they have lived in three
different places:

  * ``body_json -> board_spaces -> designs[]`` (variable count)
  * ``body_json -> feature_panels -> panels[]`` (variable count)
  * ``board_games.cp_*`` columns (one centerpiece per board)

Every cell already has a unique slug per (board, kind), and ``asset_versions``
already keys generated PNGs by ``(board_uuid, category, asset_id)`` —
``asset_id`` *is* the cell slug. Modeling cells as their own row makes that
relationship explicit (FK ``asset_versions.cell_id``), unifies the cell
status/regen flows, and lets a single query return "all cells on this board"
without three different JSON paths.

This migration:

  1. Creates ``cells`` (UUID PK + ``board_uuid`` FK) with a CHECK constraint
     enforcing kind-specific shape.
  2. Backfills one row per existing space, panel, and centerpiece.
  3. Adds ``asset_versions.cell_id`` (FK) and backfills it.
  4. Drops the centerpiece columns from ``board_games``.
  5. Strips ``board_spaces.designs`` and ``feature_panels.panels`` from
     ``body_json`` (keeping ``board_spaces.layout`` — that's geometry, not
     a cell).

Downgrade reverses the schema and rehydrates ``body_json`` / centerpiece
columns from ``cells``. Asset rows lose ``cell_id`` (column drops).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0019_promote_cells_table"
down_revision: Union[str, None] = "0018_extract_style_centerpiece"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ────────────────────────── upgrade ──────────────────────────


def upgrade() -> None:
    bind = op.get_bind()

    # 1. cells table.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()
    op.create_table(
        "cells",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "board_uuid",
            sa.String(36),
            sa.ForeignKey("board_games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("position_index", sa.Integer, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "needs_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "active_kind",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        # space-only fields
        sa.Column("space_kind", sa.String(16), nullable=True),
        sa.Column("positions_json", JSONB, nullable=True),
        # panel + centerpiece fields
        sa.Column("bbox_x1", sa.Integer, nullable=True),
        sa.Column("bbox_y1", sa.Integer, nullable=True),
        sa.Column("bbox_x2", sa.Integer, nullable=True),
        sa.Column("bbox_y2", sa.Integer, nullable=True),
        sa.Column("target_w", sa.Integer, nullable=True),
        sa.Column("target_h", sa.Integer, nullable=True),
        sa.UniqueConstraint("board_uuid", "kind", "slug", name="uq_cells_board_kind_slug"),
        sa.CheckConstraint(
            "kind IN ('space','panel','centerpiece')",
            name="ck_cells_kind_enum",
        ),
        sa.CheckConstraint(
            "active_kind IN ('glow','pulse','flicker','none')",
            name="ck_cells_active_kind_enum",
        ),
        sa.CheckConstraint(
            "space_kind IS NULL OR space_kind IN ('standard','event')",
            name="ck_cells_space_kind_enum",
        ),
        sa.CheckConstraint(
            """
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
            """,
            name="ck_cells_shape_by_kind",
        ),
    )
    op.create_index("ix_cells_board_kind", "cells", ["board_uuid", "kind"])

    # 2. Backfill spaces.
    op.execute(
        """
        INSERT INTO cells (board_uuid, kind, slug, position_index, prompt,
                           needs_active, active_kind, space_kind, positions_json)
        SELECT
            bg.id,
            'space',
            d->>'id',
            ord - 1,
            COALESCE(d->>'prompt', ''),
            FALSE,
            'none',
            COALESCE(d->>'space_kind', 'standard'),
            COALESCE(d->'positions', '[]'::jsonb)
        FROM board_games bg,
             jsonb_array_elements(bg.body_json->'board_spaces'->'designs')
                WITH ORDINALITY AS t(d, ord)
        """
    )

    # 2b. Backfill feature panels.
    op.execute(
        """
        INSERT INTO cells (board_uuid, kind, slug, position_index, prompt,
                           needs_active, active_kind,
                           bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                           target_w, target_h)
        SELECT
            bg.id,
            'panel',
            p->>'id',
            ord - 1,
            COALESCE(p->>'prompt', ''),
            COALESCE((p->>'needs_active')::boolean, FALSE),
            COALESCE(p->>'active_kind', 'none'),
            (p->'bbox'->>0)::int, (p->'bbox'->>1)::int,
            (p->'bbox'->>2)::int, (p->'bbox'->>3)::int,
            (p->'target_size'->>0)::int, (p->'target_size'->>1)::int
        FROM board_games bg,
             jsonb_array_elements(bg.body_json->'feature_panels'->'panels')
                WITH ORDINALITY AS t(p, ord)
        """
    )

    # 2c. Backfill centerpiece — exactly one per board, slug='centerpiece'.
    op.execute(
        """
        INSERT INTO cells (board_uuid, kind, slug, position_index, prompt,
                           needs_active, active_kind,
                           bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                           target_w, target_h)
        SELECT
            bg.id,
            'centerpiece',
            'centerpiece',
            0,
            bg.cp_prompt,
            bg.cp_needs_active,
            bg.cp_active_kind,
            bg.cp_bbox_x1, bg.cp_bbox_y1, bg.cp_bbox_x2, bg.cp_bbox_y2,
            bg.cp_target_w, bg.cp_target_h
        FROM board_games bg
        """
    )

    # 3. asset_versions.cell_id with backfill.
    op.add_column(
        "asset_versions",
        sa.Column(
            "cell_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cells.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE asset_versions av
        SET cell_id = c.id
        FROM cells c
        WHERE c.board_uuid = av.board_uuid
          AND c.kind = CASE av.category
                WHEN 'spaces'      THEN 'space'
                WHEN 'panels'      THEN 'panel'
                WHEN 'centerpiece' THEN 'centerpiece'
                ELSE av.category
              END
          AND c.slug = av.asset_id
        """
    )
    # Verify backfill is complete; if any row is still NULL it means a cell
    # was deleted but its history rows weren't pruned. Fail loudly so we know.
    res = bind.execute(
        sa.text("SELECT count(*) FROM asset_versions WHERE cell_id IS NULL")
    ).scalar_one()
    if res:
        raise RuntimeError(
            f"asset_versions has {res} rows that did not match any cell. "
            "Inspect (board_uuid, category, asset_id) for orphans before "
            "re-running this migration."
        )
    op.alter_column("asset_versions", "cell_id", nullable=False)
    op.create_index("ix_asset_versions_cell_id", "asset_versions", ["cell_id"])

    # 4. Drop centerpiece columns from board_games.
    for col in (
        "cp_bbox_x1", "cp_bbox_y1", "cp_bbox_x2", "cp_bbox_y2",
        "cp_target_w", "cp_target_h",
        "cp_prompt", "cp_needs_active", "cp_active_kind",
    ):
        op.drop_column("board_games", col)

    # 5. Strip designs + panels from body_json. Keep board_spaces.layout.
    op.execute(
        """
        UPDATE board_games
        SET body_json = jsonb_set(
            body_json - 'feature_panels',
            '{board_spaces}',
            (body_json->'board_spaces') - 'designs'
        )
        """
    )


# ────────────────────────── downgrade ──────────────────────────


def downgrade() -> None:
    # Reverse step 5: rebuild ``feature_panels.panels[]`` and
    # ``board_spaces.designs[]`` in body_json from the cells rows.
    op.execute(
        """
        WITH spaces_per_board AS (
            SELECT board_uuid, jsonb_agg(
                jsonb_build_object(
                    'id', slug,
                    'prompt', prompt,
                    'space_kind', space_kind,
                    'positions', positions_json
                ) ORDER BY position_index
            ) AS designs
            FROM cells WHERE kind = 'space'
            GROUP BY board_uuid
        ),
        panels_per_board AS (
            SELECT board_uuid, jsonb_agg(
                jsonb_build_object(
                    'id', slug,
                    'prompt', prompt,
                    'needs_active', needs_active,
                    'active_kind', active_kind,
                    'bbox', jsonb_build_array(bbox_x1, bbox_y1, bbox_x2, bbox_y2),
                    'target_size', jsonb_build_array(target_w, target_h)
                ) ORDER BY position_index
            ) AS panels
            FROM cells WHERE kind = 'panel'
            GROUP BY board_uuid
        )
        UPDATE board_games bg
        SET body_json = jsonb_set(
            jsonb_set(
                bg.body_json,
                '{board_spaces, designs}',
                COALESCE(s.designs, '[]'::jsonb)
            ),
            '{feature_panels}',
            jsonb_build_object('panels', COALESCE(p.panels, '[]'::jsonb))
        )
        FROM spaces_per_board s
        FULL OUTER JOIN panels_per_board p ON p.board_uuid = s.board_uuid
        WHERE bg.id = COALESCE(s.board_uuid, p.board_uuid)
        """
    )

    # Reverse step 4: re-add centerpiece columns + backfill from cells.
    op.add_column("board_games", sa.Column("cp_bbox_x1", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_bbox_y1", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_bbox_x2", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_bbox_y2", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_target_w", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_target_h", sa.Integer, nullable=False, server_default="0"))
    op.add_column("board_games", sa.Column("cp_prompt", sa.Text, nullable=False, server_default=""))
    op.add_column("board_games", sa.Column("cp_needs_active", sa.Boolean, nullable=False, server_default=sa.text("FALSE")))
    op.add_column("board_games", sa.Column("cp_active_kind", sa.String(16), nullable=False, server_default="none"))
    op.execute(
        """
        UPDATE board_games bg
        SET cp_bbox_x1 = c.bbox_x1, cp_bbox_y1 = c.bbox_y1,
            cp_bbox_x2 = c.bbox_x2, cp_bbox_y2 = c.bbox_y2,
            cp_target_w = c.target_w, cp_target_h = c.target_h,
            cp_prompt = c.prompt,
            cp_needs_active = c.needs_active,
            cp_active_kind = c.active_kind
        FROM cells c
        WHERE c.board_uuid = bg.id AND c.kind = 'centerpiece'
        """
    )

    # Reverse step 3.
    op.drop_index("ix_asset_versions_cell_id", table_name="asset_versions")
    op.drop_column("asset_versions", "cell_id")

    # Reverse step 1.
    op.drop_index("ix_cells_board_kind", table_name="cells")
    op.drop_table("cells")

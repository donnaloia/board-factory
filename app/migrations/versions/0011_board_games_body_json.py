"""Collapse the 5-table catalog into a single body_json column on board_games.

Revision ID: 0011_board_games_body_json
Revises: 0010_drop_board_catalogs
Create Date: 2026-05-02

The board catalog (style + centerpiece + board_spaces.layout + designs +
feature_panels.panels + frame + generation) was previously split across
``board_games`` scalar columns plus three child tables
(``board_space_layout_rows``, ``board_space_designs``,
``board_feature_panels``). Nothing queries those tables by their own
columns — they exist only so that ``load_catalog_dict`` can reassemble
the original nested dict.

This migration:

  1. Adds ``board_games.body_json`` (nullable initially).
  2. Walks every existing ``board_games`` row, reassembles the nested
     catalog dict from the child tables (using the same logic the service
     layer used), validates via Pydantic, and writes the JSON blob to
     ``body_json``.
  3. Makes ``body_json`` NOT NULL.
  4. Drops the now-orphaned child tables and the
     ``generation_json`` / ``frame_json`` / per-field scalar columns on
     ``board_games``. ``palette_json``, ``palette_gpl_text``,
     ``style_lock_updated_ms`` are kept — they have a separate writer
     (``services.workspace_palette``) and are materialized to disk on
     job start.

Downgrade rebuilds the child tables empty; **catalog data is not
restored** on downgrade because nobody reads the old shape anymore.
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_body_json"
down_revision: Union[str, None] = "0010_drop_board_catalogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEGACY_BOARD_GAMES_COLUMNS = (
    "project",
    "board_size_w",
    "board_size_h",
    "style_reference_image",
    "style_prompt",
    "cp_bbox_x1",
    "cp_bbox_y1",
    "cp_bbox_x2",
    "cp_bbox_y2",
    "cp_target_w",
    "cp_target_h",
    "cp_prompt",
    "cp_needs_active",
    "cp_active_kind",
    "generation_json",
    "frame_json",
)


def _read_layout_rows(conn, board_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        sa.text(
            """
            SELECT row_key, count, start_x, start_y, spacing, axis, size_w, size_h
            FROM board_space_layout_rows
            WHERE board_id = :bid
            ORDER BY sort_order, id
            """
        ),
        {"bid": board_id},
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r.row_key] = {
            "count": int(r.count),
            "start": [int(r.start_x), int(r.start_y)],
            "spacing": int(r.spacing),
            "axis": str(r.axis),
            "size": [int(r.size_w), int(r.size_h)],
        }
    return out


def _read_designs(conn, board_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        sa.text(
            """
            SELECT design_id, prompt, space_kind, positions_json
            FROM board_space_designs
            WHERE board_id = :bid
            ORDER BY sort_order, id
            """
        ),
        {"bid": board_id},
    ).fetchall()
    return [
        {
            "id": r.design_id,
            "prompt": r.prompt,
            "space_kind": r.space_kind or "standard",
            "positions": json.loads(r.positions_json or "[]"),
        }
        for r in rows
    ]


def _read_panels(conn, board_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        sa.text(
            """
            SELECT panel_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                   target_w, target_h, prompt, needs_active, active_kind
            FROM board_feature_panels
            WHERE board_id = :bid
            ORDER BY sort_order, id
            """
        ),
        {"bid": board_id},
    ).fetchall()
    return [
        {
            "id": r.panel_id,
            "bbox": [int(r.bbox_x1), int(r.bbox_y1), int(r.bbox_x2), int(r.bbox_y2)],
            "target_size": [int(r.target_w), int(r.target_h)],
            "prompt": r.prompt,
            "needs_active": bool(r.needs_active),
            "active_kind": r.active_kind or "none",
        }
        for r in rows
    ]


def _reassemble(conn, row: sa.engine.Row) -> dict[str, Any]:
    bid = row.board_id
    layout = _read_layout_rows(conn, bid)
    designs = _read_designs(conn, bid)
    panels = _read_panels(conn, bid)
    generation = json.loads(row.generation_json or "{}")
    frame = json.loads(row.frame_json or "{}")
    return {
        "project": row.project,
        "board_size": [int(row.board_size_w), int(row.board_size_h)],
        "style": {
            "reference_image": row.style_reference_image,
            "palette_size": int(generation.get("palette_size", 36)),
            "prompt": row.style_prompt,
        },
        "centerpiece": {
            "bbox": [int(row.cp_bbox_x1), int(row.cp_bbox_y1),
                     int(row.cp_bbox_x2), int(row.cp_bbox_y2)],
            "target_size": [int(row.cp_target_w), int(row.cp_target_h)],
            "prompt": row.cp_prompt,
            "needs_active": bool(row.cp_needs_active),
            "active_kind": row.cp_active_kind or "none",
        },
        "board_spaces": {"layout": layout, "designs": designs},
        "feature_panels": {"panels": panels},
        "frame": frame,
        "generation": generation,
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("board_games")}

    if "body_json" not in cols:
        op.add_column("board_games", sa.Column("body_json", sa.Text(), nullable=True))

    # Backfill body_json by walking child tables.
    legacy_present = {
        "board_space_layout_rows",
        "board_space_designs",
        "board_feature_panels",
    }.issubset(set(inspector.get_table_names()))

    select_cols = ", ".join(["board_id", *_LEGACY_BOARD_GAMES_COLUMNS])
    if legacy_present:
        rows = bind.execute(
            sa.text(f"SELECT {select_cols} FROM board_games WHERE body_json IS NULL")
        ).fetchall()
        for row in rows:
            data = _reassemble(bind, row)
            bind.execute(
                sa.text("UPDATE board_games SET body_json = :body WHERE board_id = :bid"),
                {"body": json.dumps(data, ensure_ascii=False), "bid": row.board_id},
            )

    # Make body_json NOT NULL now that every row has it.
    with op.batch_alter_table("board_games") as batch:
        batch.alter_column("body_json", nullable=False)

    # Drop the now-redundant per-field scalar columns and the JSON sub-blobs.
    legacy_cols_to_drop = [
        "project",
        "board_size_w",
        "board_size_h",
        "style_reference_image",
        "style_prompt",
        "cp_bbox_x1",
        "cp_bbox_y1",
        "cp_bbox_x2",
        "cp_bbox_y2",
        "cp_target_w",
        "cp_target_h",
        "cp_prompt",
        "cp_needs_active",
        "cp_active_kind",
        "generation_json",
        "frame_json",
    ]
    with op.batch_alter_table("board_games") as batch:
        for c in legacy_cols_to_drop:
            if c in cols:
                batch.drop_column(c)

    # Drop the legacy child tables.
    for table_name, index_name in (
        ("board_feature_panels", "ix_board_feature_panels_board_panel"),
        ("board_space_designs", "ix_board_space_designs_board_design"),
        ("board_space_layout_rows", "ix_board_space_layout_board_row"),
    ):
        if table_name in inspector.get_table_names():
            try:
                op.drop_index(index_name, table_name=table_name)
            except Exception:
                pass
            op.drop_table(table_name)


def downgrade() -> None:
    # Re-add the legacy scalar columns and child tables empty. We do NOT
    # try to round-trip the body_json blob back into the normalized form -
    # nothing reads it that way anymore.
    with op.batch_alter_table("board_games") as batch:
        batch.add_column(sa.Column("project", sa.String(length=512), nullable=False, server_default=""))
        batch.add_column(sa.Column("board_size_w", sa.Integer(), nullable=False, server_default="0"))  # noqa: E501
        batch.add_column(sa.Column("board_size_h", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("style_reference_image", sa.String(length=512), nullable=False, server_default=""))
        batch.add_column(sa.Column("style_prompt", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("cp_bbox_x1", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_bbox_y1", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_bbox_x2", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_bbox_y2", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_target_w", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_target_h", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_prompt", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("cp_needs_active", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cp_active_kind", sa.String(length=16), nullable=False, server_default="none"))
        batch.add_column(sa.Column("generation_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("frame_json", sa.Text(), nullable=False, server_default="{}"))
        batch.alter_column("body_json", nullable=True)

    op.create_table(
        "board_space_layout_rows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_key", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("start_x", sa.Integer(), nullable=False),
        sa.Column("start_y", sa.Integer(), nullable=False),
        sa.Column("spacing", sa.Integer(), nullable=False),
        sa.Column("axis", sa.String(length=1), nullable=False),
        sa.Column("size_w", sa.Integer(), nullable=False),
        sa.Column("size_h", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_space_layout_board_row",
        "board_space_layout_rows",
        ["board_id", "row_key"],
        unique=True,
    )

    op.create_table(
        "board_space_designs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("design_id", sa.String(length=256), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("space_kind", sa.String(length=16), nullable=False, server_default="standard"),
        sa.Column("positions_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_space_designs_board_design",
        "board_space_designs",
        ["board_id", "design_id"],
        unique=True,
    )

    op.create_table(
        "board_feature_panels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("panel_id", sa.String(length=256), nullable=False),
        sa.Column("bbox_x1", sa.Integer(), nullable=False),
        sa.Column("bbox_y1", sa.Integer(), nullable=False),
        sa.Column("bbox_x2", sa.Integer(), nullable=False),
        sa.Column("bbox_y2", sa.Integer(), nullable=False),
        sa.Column("target_w", sa.Integer(), nullable=False),
        sa.Column("target_h", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("needs_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("active_kind", sa.String(length=16), nullable=False, server_default="none"),
        sa.ForeignKeyConstraint(["board_id"], ["board_games.board_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_board_feature_panels_board_panel",
        "board_feature_panels",
        ["board_id", "panel_id"],
        unique=True,
    )

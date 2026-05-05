"""Promote scalar ``style`` and ``centerpiece`` fields to columns.

Revision ID: 0018_extract_style_centerpiece
Revises: 0017_extract_catalog_columns
Create Date: 2026-05-04

After ``0017`` the ``board_games.body_json`` blob held only:

  * ``style`` (reference_image, prompt, palette_size mirror)
  * ``centerpiece`` (bbox, target_size, prompt, needs_active, active_kind)
  * ``board_spaces`` (variable-length layout + designs)
  * ``feature_panels`` (variable-length panels list)

The first two are *fixed-shape scalar bundles* — they have a constant set of
fields and there's no growth dimension. Promoting them to columns leaves
``body_json`` holding only the genuinely variable-length collections, which
matches the typed-columns / JSONB split rule of thumb: scalars become
columns; arrays/maps stay JSONB.

The ``style.palette_size`` mirror is not promoted: it duplicates the
``palette_size`` column added in ``0017``. The Pydantic ``Catalog`` validator
fills it back in at read time so legacy pipeline code (``steps/style_lock``)
that reads ``catalog.style.palette_size`` keeps working.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_extract_style_centerpiece"
down_revision: Union[str, None] = "0017_extract_catalog_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the new columns as nullable so the backfill can fill them in
    #    without violating NOT NULL.
    op.add_column("board_games", sa.Column("style_reference_image", sa.String(length=1024), nullable=True))
    op.add_column("board_games", sa.Column("style_prompt", sa.Text(), nullable=True))

    op.add_column("board_games", sa.Column("cp_bbox_x1", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_bbox_y1", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_bbox_x2", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_bbox_y2", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_target_w", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_target_h", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("cp_prompt", sa.Text(), nullable=True))
    op.add_column("board_games", sa.Column("cp_needs_active", sa.Boolean(), nullable=True))
    op.add_column("board_games", sa.Column("cp_active_kind", sa.String(length=16), nullable=True))

    # 2. Backfill from body_json. SQLAlchemy hydrates JSONB into a Python dict.
    rows = bind.execute(sa.text("SELECT id, body_json FROM board_games")).fetchall()
    for row in rows:
        body = row.body_json or {}

        ref = str(_get(body, "style", "reference_image", default="") or "")
        prompt = str(_get(body, "style", "prompt", default="") or "")

        bbox = _get(body, "centerpiece", "bbox") or [0, 0, 0, 0]
        try:
            bbox = [int(bbox[i]) if i < len(bbox) else 0 for i in range(4)]
        except (TypeError, ValueError):
            bbox = [0, 0, 0, 0]

        ts = _get(body, "centerpiece", "target_size") or [0, 0]
        try:
            tw = int(ts[0]) if len(ts) >= 1 else 0
            th = int(ts[1]) if len(ts) >= 2 else 0
        except (TypeError, ValueError):
            tw, th = 0, 0

        cp_prompt = str(_get(body, "centerpiece", "prompt", default="") or "")
        cp_needs_active = bool(_get(body, "centerpiece", "needs_active", default=False))
        cp_active_kind = str(_get(body, "centerpiece", "active_kind", default="none") or "none")
        if cp_active_kind not in ("glow", "pulse", "flicker", "none"):
            cp_active_kind = "none"

        bind.execute(
            sa.text(
                """
                UPDATE board_games SET
                    style_reference_image = :ref,
                    style_prompt = :sp,
                    cp_bbox_x1 = :x1,
                    cp_bbox_y1 = :y1,
                    cp_bbox_x2 = :x2,
                    cp_bbox_y2 = :y2,
                    cp_target_w = :tw,
                    cp_target_h = :th,
                    cp_prompt = :cpp,
                    cp_needs_active = :na,
                    cp_active_kind = :ak
                WHERE id = :id
                """
            ),
            {
                "id": row.id,
                "ref": ref,
                "sp": prompt,
                "x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3],
                "tw": tw, "th": th,
                "cpp": cp_prompt,
                "na": cp_needs_active,
                "ak": cp_active_kind,
            },
        )

    # 3. Lock the columns down. Defaults match what the Pydantic validators
    #    treat as "empty / unconfigured".
    op.alter_column(
        "board_games", "style_reference_image", existing_type=sa.String(length=1024),
        nullable=False, server_default=sa.text("''"),
    )
    op.alter_column(
        "board_games", "style_prompt", existing_type=sa.Text(),
        nullable=False, server_default=sa.text("''"),
    )
    for col in ("cp_bbox_x1", "cp_bbox_y1", "cp_bbox_x2", "cp_bbox_y2",
                "cp_target_w", "cp_target_h"):
        op.alter_column(
            "board_games", col, existing_type=sa.Integer(),
            nullable=False, server_default=sa.text("0"),
        )
    op.alter_column(
        "board_games", "cp_prompt", existing_type=sa.Text(),
        nullable=False, server_default=sa.text("''"),
    )
    op.alter_column(
        "board_games", "cp_needs_active", existing_type=sa.Boolean(),
        nullable=False, server_default=sa.text("FALSE"),
    )
    op.alter_column(
        "board_games", "cp_active_kind", existing_type=sa.String(length=16),
        nullable=False, server_default=sa.text("'none'"),
    )

    # 4. Strip the now-promoted keys out of body_json so the columns are the
    #    single source of truth. After this body_json holds only the
    #    variable-length collections (board_spaces, feature_panels).
    op.execute(
        """
        UPDATE board_games
        SET body_json = body_json
            - 'style'
            - 'centerpiece'
        """
    )


def downgrade() -> None:
    import json

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, body_json,
                   style_reference_image, style_prompt, palette_size,
                   cp_bbox_x1, cp_bbox_y1, cp_bbox_x2, cp_bbox_y2,
                   cp_target_w, cp_target_h, cp_prompt, cp_needs_active, cp_active_kind
            FROM board_games
            """
        )
    ).fetchall()
    for r in rows:
        body = dict(r.body_json or {})
        body["style"] = {
            "reference_image": r.style_reference_image,
            "prompt": r.style_prompt,
            # ``palette_size`` mirror, restored from the column added in 0017.
            "palette_size": int(r.palette_size),
        }
        body["centerpiece"] = {
            "bbox": [int(r.cp_bbox_x1), int(r.cp_bbox_y1),
                     int(r.cp_bbox_x2), int(r.cp_bbox_y2)],
            "target_size": [int(r.cp_target_w), int(r.cp_target_h)],
            "prompt": r.cp_prompt,
            "needs_active": bool(r.cp_needs_active),
            "active_kind": r.cp_active_kind or "none",
        }
        bind.execute(
            sa.text("UPDATE board_games SET body_json = CAST(:b AS JSONB) WHERE id = :id"),
            {"b": json.dumps(body), "id": r.id},
        )

    for col in (
        "cp_active_kind", "cp_needs_active", "cp_prompt",
        "cp_target_h", "cp_target_w",
        "cp_bbox_y2", "cp_bbox_x2", "cp_bbox_y1", "cp_bbox_x1",
        "style_prompt", "style_reference_image",
    ):
        op.drop_column("board_games", col)

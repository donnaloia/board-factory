"""Promote stable catalog header fields into typed columns on ``board_games``.

Revision ID: 0017_extract_catalog_columns
Revises: 0016_body_json_to_jsonb
Create Date: 2026-05-04

Background
----------

Since revision ``0011_body_json_to_jsonb`` the entire catalog has been a
single JSONB blob in ``board_games.body_json``. That kept persistence cheap
during the consolidation phase, but it forces every "is this board using
provider X?" or "what's its display name?" query to load and Pydantic-validate
the whole nested structure.

This migration promotes the *stable header fields* — values that are always
present, are part of the board's identity or top-level configuration, and are
read on hot paths (list pages, generation kick-off, settings modal) — into
typed columns:

  * ``project``                       (display name, sortable)
  * ``board_size_w``, ``board_size_h``
  * ``palette_size``, ``provider``
  * ``openai_model``, ``openai_quality``
  * ``pixellab_model``
  * ``generation_configured``
  * ``frame_enabled``, ``frame_apply_to_panels``, ``frame_apply_to_spaces``

What stays in ``body_json``
---------------------------

The genuinely variable parts of the catalog:

  * ``style`` (reference_image + free-text prompt)
  * ``centerpiece`` (one nested object, never queried)
  * ``board_spaces.layout`` and ``board_spaces.designs`` (variable list)
  * ``feature_panels.panels`` (variable list)

Pydantic ``Catalog`` validation is unchanged: the ``services.board_definition``
layer assembles the legacy nested dict from columns + JSONB at read time, and
decomposes it back at write time.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_extract_catalog_columns"
down_revision: Union[str, None] = "0016_body_json_to_jsonb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Defaults match ``boardfactory.schemas.catalog.GenerationSpec``.
_DEFAULT_PALETTE_SIZE = 36
_DEFAULT_PROVIDER = "openai"
_DEFAULT_OPENAI_MODEL = "gpt-image-2"
_DEFAULT_OPENAI_QUALITY = "low"
_DEFAULT_PIXELLAB_MODEL = "pixflux_sharp"


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
    #    one row at a time without violating NOT NULL constraints.
    op.add_column("board_games", sa.Column("project", sa.String(length=512), nullable=True))
    op.add_column("board_games", sa.Column("board_size_w", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("board_size_h", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("palette_size", sa.Integer(), nullable=True))
    op.add_column("board_games", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("board_games", sa.Column("openai_model", sa.String(length=64), nullable=True))
    op.add_column("board_games", sa.Column("openai_quality", sa.String(length=16), nullable=True))
    op.add_column("board_games", sa.Column("pixellab_model", sa.String(length=64), nullable=True))
    op.add_column("board_games", sa.Column("generation_configured", sa.Boolean(), nullable=True))
    op.add_column("board_games", sa.Column("frame_enabled", sa.Boolean(), nullable=True))
    op.add_column("board_games", sa.Column("frame_apply_to_panels", sa.Boolean(), nullable=True))
    op.add_column("board_games", sa.Column("frame_apply_to_spaces", sa.Boolean(), nullable=True))

    # 2. Backfill from body_json. We read the JSONB blob via SQLAlchemy so it
    #    arrives as a Python dict (no manual json.loads needed).
    rows = bind.execute(sa.text("SELECT id, body_json FROM board_games")).fetchall()
    for row in rows:
        body = row.body_json or {}
        project = str(_get(body, "project") or "")
        board_size = _get(body, "board_size") or [0, 0]
        try:
            board_size_w = int(board_size[0]) if len(board_size) >= 1 else 0
            board_size_h = int(board_size[1]) if len(board_size) >= 2 else 0
        except (TypeError, ValueError):
            board_size_w = 0
            board_size_h = 0

        palette_size = _get(body, "generation", "palette_size", default=None)
        if palette_size is None:
            # Fall back to the legacy mirror under ``style.palette_size``.
            palette_size = _get(body, "style", "palette_size", default=_DEFAULT_PALETTE_SIZE)
        try:
            palette_size = int(palette_size)
        except (TypeError, ValueError):
            palette_size = _DEFAULT_PALETTE_SIZE

        provider = _get(body, "generation", "provider", default=_DEFAULT_PROVIDER)
        openai_model = _get(body, "generation", "openai", "model", default=_DEFAULT_OPENAI_MODEL)
        openai_quality = _get(
            body, "generation", "openai", "quality", default=_DEFAULT_OPENAI_QUALITY
        )
        pixellab_model = _get(
            body, "generation", "pixellab", "model", default=_DEFAULT_PIXELLAB_MODEL
        )
        generation_configured = bool(_get(body, "generation", "configured", default=False))

        frame_enabled = bool(_get(body, "frame", "enabled", default=False))
        frame_apply_to_panels = bool(_get(body, "frame", "apply_to_panels", default=True))
        frame_apply_to_spaces = bool(_get(body, "frame", "apply_to_spaces", default=False))

        bind.execute(
            sa.text(
                """
                UPDATE board_games SET
                    project = :project,
                    board_size_w = :w,
                    board_size_h = :h,
                    palette_size = :ps,
                    provider = :prov,
                    openai_model = :om,
                    openai_quality = :oq,
                    pixellab_model = :pm,
                    generation_configured = :gc,
                    frame_enabled = :fe,
                    frame_apply_to_panels = :fp,
                    frame_apply_to_spaces = :fs
                WHERE id = :id
                """
            ),
            {
                "id": row.id,
                "project": project,
                "w": board_size_w,
                "h": board_size_h,
                "ps": palette_size,
                "prov": provider,
                "om": openai_model,
                "oq": openai_quality,
                "pm": pixellab_model,
                "gc": generation_configured,
                "fe": frame_enabled,
                "fp": frame_apply_to_panels,
                "fs": frame_apply_to_spaces,
            },
        )

    # 3. Lock the columns down. Defaults make future inserts via Core/ORM
    #    forgiving when callers omit a field (the Pydantic-side ``Catalog``
    #    still fills sensible defaults at validation time).
    op.alter_column(
        "board_games", "project", existing_type=sa.String(length=512),
        nullable=False, server_default=sa.text("''"),
    )
    op.alter_column(
        "board_games", "board_size_w", existing_type=sa.Integer(),
        nullable=False, server_default=sa.text("0"),
    )
    op.alter_column(
        "board_games", "board_size_h", existing_type=sa.Integer(),
        nullable=False, server_default=sa.text("0"),
    )
    op.alter_column(
        "board_games", "palette_size", existing_type=sa.Integer(),
        nullable=False, server_default=sa.text(str(_DEFAULT_PALETTE_SIZE)),
    )
    op.alter_column(
        "board_games", "provider", existing_type=sa.String(length=32),
        nullable=False, server_default=sa.text(f"'{_DEFAULT_PROVIDER}'"),
    )
    op.alter_column(
        "board_games", "openai_model", existing_type=sa.String(length=64),
        nullable=False, server_default=sa.text(f"'{_DEFAULT_OPENAI_MODEL}'"),
    )
    op.alter_column(
        "board_games", "openai_quality", existing_type=sa.String(length=16),
        nullable=False, server_default=sa.text(f"'{_DEFAULT_OPENAI_QUALITY}'"),
    )
    op.alter_column(
        "board_games", "pixellab_model", existing_type=sa.String(length=64),
        nullable=False, server_default=sa.text(f"'{_DEFAULT_PIXELLAB_MODEL}'"),
    )
    op.alter_column(
        "board_games", "generation_configured", existing_type=sa.Boolean(),
        nullable=False, server_default=sa.text("FALSE"),
    )
    op.alter_column(
        "board_games", "frame_enabled", existing_type=sa.Boolean(),
        nullable=False, server_default=sa.text("FALSE"),
    )
    op.alter_column(
        "board_games", "frame_apply_to_panels", existing_type=sa.Boolean(),
        nullable=False, server_default=sa.text("TRUE"),
    )
    op.alter_column(
        "board_games", "frame_apply_to_spaces", existing_type=sa.Boolean(),
        nullable=False, server_default=sa.text("FALSE"),
    )

    # 4. Strip the now-promoted keys out of body_json so the column is the
    #    single source of truth. body_json keeps style / centerpiece /
    #    board_spaces / feature_panels.
    op.execute(
        """
        UPDATE board_games
        SET body_json = body_json
            - 'project'
            - 'board_size'
            - 'generation'
            - 'frame'
        """
    )


def downgrade() -> None:
    # Re-embed the columns into body_json so the previous shape works again.
    import json

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, body_json, project, board_size_w, board_size_h,
                   palette_size, provider, openai_model, openai_quality,
                   pixellab_model, generation_configured,
                   frame_enabled, frame_apply_to_panels, frame_apply_to_spaces
            FROM board_games
            """
        )
    ).fetchall()
    for r in rows:
        body = dict(r.body_json or {})
        body["project"] = r.project
        body["board_size"] = [int(r.board_size_w), int(r.board_size_h)]
        body["generation"] = {
            "palette_size": int(r.palette_size),
            "provider": r.provider,
            "openai": {"model": r.openai_model, "quality": r.openai_quality},
            "pixellab": {"model": r.pixellab_model},
            "configured": bool(r.generation_configured),
        }
        body["frame"] = {
            "enabled": bool(r.frame_enabled),
            "apply_to_panels": bool(r.frame_apply_to_panels),
            "apply_to_spaces": bool(r.frame_apply_to_spaces),
        }
        # Re-mirror palette_size into style for the legacy synchronizer.
        style = body.get("style") or {}
        if isinstance(style, dict):
            style["palette_size"] = int(r.palette_size)
            body["style"] = style
        bind.execute(
            sa.text("UPDATE board_games SET body_json = CAST(:b AS JSONB) WHERE id = :id"),
            {"b": json.dumps(body), "id": r.id},
        )

    for col in (
        "frame_apply_to_spaces",
        "frame_apply_to_panels",
        "frame_enabled",
        "generation_configured",
        "pixellab_model",
        "openai_quality",
        "openai_model",
        "provider",
        "palette_size",
        "board_size_h",
        "board_size_w",
        "project",
    ):
        op.drop_column("board_games", col)

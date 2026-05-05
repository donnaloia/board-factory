"""Convert ``board_games.body_json`` from TEXT to JSONB.

Revision ID: 0016_body_json_to_jsonb
Revises: 0015_board_uuid_user_paths
Create Date: 2026-05-04

The catalog blob has been a ``TEXT`` column ever since revision
``0011_body_json_to_jsonb`` collapsed the previously-relational catalog
schema. Switching to ``JSONB`` lets us:

* Indexed lookups into the blob (``body_json -> 'generation' ->> 'provider'``).
* Hand-typed JSON in ad-hoc psql queries instead of escaping a string.
* Skip the Python-side ``json.loads`` round trip in ``board_definition``.

Postgres-only — the SQLite fallback was removed in the prior commit, so we
don't need a ``batch_alter_table`` shim here.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0016_body_json_to_jsonb"
down_revision: Union[str, None] = "0015_board_uuid_user_paths"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE board_games "
        "ALTER COLUMN body_json TYPE JSONB USING body_json::jsonb"
    )


def downgrade() -> None:
    # JSONB -> TEXT is lossy for ordering of object keys but every reader
    # treats body_json as a dict, so this is safe in practice.
    op.execute(
        "ALTER TABLE board_games "
        "ALTER COLUMN body_json TYPE TEXT USING body_json::text"
    )

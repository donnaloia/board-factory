"""Data: rename board id untitled-board-mopxc3av -> demo-board.

Revision ID: 0013_rename_demo_board
Revises: 0012_user_board_urls

Aligns relational rows with a renamed on-disk board directory
(``data/boards/<board_id>/`` or ``BOARDFACTORY_BOARDS_DIR``).

Run **after** renaming the folder, or ensure nothing touches the DB until both
are applied. On databases that never had ``OLD_BOARD_ID``, updates affect zero
rows (safe no-op).

Downgrade reverses the string swap (destructive if ``demo-board`` was reused
for another purpose after upgrade).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_rename_demo_board"
down_revision: Union[str, None] = "0012_user_board_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_BOARD_ID = "untitled-board-mopxc3av"
NEW_BOARD_ID = "demo-board"


def upgrade() -> None:
    conn = op.get_bind()
    p = {"old": OLD_BOARD_ID, "new": NEW_BOARD_ID}

    conn.execute(
        sa.text("UPDATE board_games SET board_id = :new WHERE board_id = :old"),
        p,
    )
    conn.execute(
        sa.text("UPDATE asset_versions SET board_id = :new WHERE board_id = :old"),
        p,
    )
    conn.execute(
        sa.text(
            "UPDATE owned_boards SET board_id = :new, path_slug = :new "
            "WHERE board_id = :old"
        ),
        p,
    )
    conn.execute(
        sa.text("UPDATE job_runs SET target = :new WHERE target = :old"),
        p,
    )
    conn.execute(
        sa.text("UPDATE cost_entries SET target = :new WHERE target = :old"),
        p,
    )


def downgrade() -> None:
    conn = op.get_bind()
    p = {"old": NEW_BOARD_ID, "new": OLD_BOARD_ID}

    conn.execute(
        sa.text("UPDATE board_games SET board_id = :new WHERE board_id = :old"),
        p,
    )
    conn.execute(
        sa.text("UPDATE asset_versions SET board_id = :new WHERE board_id = :old"),
        p,
    )
    conn.execute(
        sa.text(
            "UPDATE owned_boards SET board_id = :new, path_slug = :new "
            "WHERE board_id = :old"
        ),
        p,
    )
    conn.execute(
        sa.text("UPDATE job_runs SET target = :new WHERE target = :old"),
        p,
    )
    conn.execute(
        sa.text("UPDATE cost_entries SET target = :new WHERE target = :old"),
        p,
    )

"""UUID primary keys + ``<user_id>/<board_uuid>/`` on-disk layout.

Revision ID: 0015_board_uuid_user_paths
Revises: 0014_owned_boards_list_order

- ``board_games.id`` (UUID string, PK) replaces ``board_id``.
- ``owned_boards.board_uuid`` FK → ``board_games.id``; URL segment stays in ``path_slug``.
- ``asset_versions.board_uuid`` replaces ``board_id``.
- On-disk: moves ``<boards-dir>/<old-slug>/`` → ``<boards-dir>/<user_id>/<uuid>/``.

Dialects: **SQLite** (``AUTOINCREMENT`` + ``PRAGMA foreign_keys``) and **PostgreSQL**
(``SERIAL`` for ``asset_versions.id``).
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0015_board_uuid_user_paths"
down_revision: Union[str, None] = "0014_owned_boards_list_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _boards_root() -> Path:
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "."))
    return repo / "data" / "boards"


def _drop_board_tables(conn) -> None:
    """Remove dependent tables in FK-safe order.

    PostgreSQL enforces FK checks during DDL inside a transaction; SQLite needs
    ``PRAGMA foreign_keys=OFF`` around the same drops (handled by caller).
    """
    conn.execute(text("DROP TABLE IF EXISTS asset_versions"))
    conn.execute(text("DROP TABLE IF EXISTS owned_boards"))
    conn.execute(text("DROP TABLE IF EXISTS board_games"))


def _create_schema(conn, *, is_sqlite: bool) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE board_games (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                body_json TEXT NOT NULL,
                updated_ms BIGINT NOT NULL,
                palette_json TEXT,
                palette_gpl_text TEXT,
                style_lock_updated_ms BIGINT
            )
            """
        )
    )

    conn.execute(
        text(
            """
            CREATE TABLE owned_boards (
                board_uuid VARCHAR(36) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                path_slug VARCHAR(128) NOT NULL,
                created_ms BIGINT NOT NULL,
                list_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(board_uuid) REFERENCES board_games(id) ON DELETE CASCADE,
                UNIQUE (user_id, path_slug)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_owned_boards_user_id ON owned_boards (user_id)"))

    id_col = (
        "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT"
        if is_sqlite
        else "id SERIAL NOT NULL PRIMARY KEY"
    )
    conn.execute(
        text(
            f"""
            CREATE TABLE asset_versions (
                {id_col},
                board_uuid VARCHAR(36) NOT NULL,
                category VARCHAR(32) NOT NULL,
                asset_id VARCHAR(256) NOT NULL,
                basename VARCHAR(512) NOT NULL,
                rel_path VARCHAR(512) NOT NULL,
                sha256 VARCHAR(64),
                ts_ms BIGINT NOT NULL,
                meta_json TEXT,
                FOREIGN KEY(board_uuid) REFERENCES board_games(id) ON DELETE CASCADE
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX ix_asset_versions_board_cell ON asset_versions "
            "(board_uuid, category, asset_id)"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX ix_asset_versions_board_relpath ON asset_versions "
            "(board_uuid, rel_path)"
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError(
            f"0015_board_uuid_user_paths: unsupported dialect {dialect!r}; "
            "expected sqlite or postgresql."
        )
    is_sqlite = dialect == "sqlite"

    bg_rows = conn.execute(
        text(
            "SELECT board_id, body_json, updated_ms, palette_json, palette_gpl_text, "
            "style_lock_updated_ms FROM board_games"
        )
    ).mappings().all()

    ob_rows = conn.execute(
        text(
            "SELECT board_id, user_id, path_slug, created_ms, list_order FROM owned_boards"
        )
    ).mappings().all()

    av_rows = conn.execute(text("SELECT * FROM asset_versions")).mappings().all()

    old_to_uuid: dict[str, str] = {r["board_id"]: str(uuid.uuid4()) for r in bg_rows}

    if is_sqlite:
        conn.execute(text("PRAGMA foreign_keys=OFF"))

    _drop_board_tables(conn)
    _create_schema(conn, is_sqlite=is_sqlite)

    for r in bg_rows:
        nid = old_to_uuid[r["board_id"]]
        conn.execute(
            text(
                "INSERT INTO board_games (id, body_json, updated_ms, palette_json, "
                "palette_gpl_text, style_lock_updated_ms) VALUES "
                "(:id, :bj, :um, :pj, :pg, :sl)"
            ),
            {
                "id": nid,
                "bj": r["body_json"],
                "um": r["updated_ms"],
                "pj": r["palette_json"],
                "pg": r["palette_gpl_text"],
                "sl": r["style_lock_updated_ms"],
            },
        )

    for r in ob_rows:
        oid = r["board_id"]
        if oid not in old_to_uuid:
            continue
        conn.execute(
            text(
                "INSERT INTO owned_boards (board_uuid, user_id, path_slug, created_ms, list_order) "
                "VALUES (:bu, :uid, :ps, :cm, :lo)"
            ),
            {
                "bu": old_to_uuid[oid],
                "uid": r["user_id"],
                "ps": r["path_slug"],
                "cm": r["created_ms"],
                "lo": r["list_order"],
            },
        )

    for r in av_rows:
        oid = r["board_id"]
        nu = old_to_uuid.get(oid)
        if nu is None:
            continue
        conn.execute(
            text(
                "INSERT INTO asset_versions (board_uuid, category, asset_id, basename, "
                "rel_path, sha256, ts_ms, meta_json) VALUES "
                "(:bu, :cat, :aid, :bn, :rp, :sh, :ts, :mj)"
            ),
            {
                "bu": nu,
                "cat": r["category"],
                "aid": r["asset_id"],
                "bn": r["basename"],
                "rp": r["rel_path"],
                "sh": r["sha256"],
                "ts": r["ts_ms"],
                "mj": r["meta_json"],
            },
        )

    if is_sqlite:
        conn.execute(text("PRAGMA foreign_keys=ON"))

    root = _boards_root()
    if not root.exists():
        return

    for r in ob_rows:
        old_slug = r["board_id"]
        uid = r["user_id"]
        nu = old_to_uuid.get(old_slug)
        if nu is None:
            continue
        src = root / old_slug
        dst_dir = root / uid
        dst = dst_dir / nu
        if src.is_dir() and not dst.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))


def downgrade() -> None:
    raise NotImplementedError("UUID layout downgrade is not supported")

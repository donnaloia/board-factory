"""Application startup: migrate DB schema + one-time file imports."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def _alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[1] / "alembic.ini"


def upgrade_schema_to_head() -> None:
    ini = _alembic_ini_path()
    cfg = Config(str(ini))
    # ``script_location = migrations`` in alembic.ini is resolved relative to
    # process cwd; uvicorn/pytest often run with cwd ``/app`` while tests mount
    # the repo elsewhere — pin an absolute path so upgrades always find scripts.
    cfg.set_main_option("script_location", str(ini.parent / "migrations"))
    command.upgrade(cfg, "head")


def register_pipeline_hooks() -> None:
    """Wire optional listeners into ``boardfactory.assets`` (DB-backed asset index)."""
    try:
        from boardfactory import assets as bf_assets  # noqa: PLC0415
        from services import asset_index  # noqa: PLC0415

        bf_assets.register_asset_db_listener(asset_index.on_asset_event)
    except Exception as exc:
        print(f"[bootstrap] pipeline hooks skipped: {exc}")


def _run_deferred_maintenance() -> None:
    """Filesystem-heavy maintenance — must not block listening on the HTTP port."""
    t0 = time.monotonic()
    logger.info("bootstrap: deferred maintenance starting")
    try:
        try:
            from services import asset_index  # noqa: PLC0415

            asset_index.backfill_all_boards_with_catalog()
        except Exception as exc:
            print(f"[bootstrap] asset index backfill skipped: {exc}")
        try:
            from services import workspace_palette as _wpl  # noqa: PLC0415

            _wpl.migrate_palette_from_disk_all_boards()
        except Exception as exc:
            print(f"[bootstrap] workspace DB migration helpers skipped: {exc}")
    finally:
        logger.info(
            "bootstrap: deferred maintenance finished in %.2fs",
            time.monotonic() - t0,
        )


def apply() -> None:
    """Idempotent: Alembic upgrade + legacy JSON / JSONL imports."""
    t_alembic = time.monotonic()
    logger.info("bootstrap: Alembic upgrade → head")
    upgrade_schema_to_head()
    logger.info("bootstrap: Alembic finished in %.2fs", time.monotonic() - t_alembic)

    try:
        from services import board_ownership as _bo  # noqa: PLC0415

        _bo.backfill_owned_boards_if_empty()
    except Exception as exc:
        print(f"[bootstrap] owned_board backfill skipped: {exc}")
    register_pipeline_hooks()

    # Large scans (PNG history walk, disk migrations) run in a daemon thread so
    # uvicorn can accept connections immediately — avoiding “browser spins forever”.
    if os.environ.get("BOARDFACTORY_SYNC_DEFERRED_BOOTSTRAP", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        _run_deferred_maintenance()
    else:
        threading.Thread(
            target=_run_deferred_maintenance,
            name="bf-deferred-bootstrap",
            daemon=True,
        ).start()

"""Application startup: migrate DB schema + one-time file imports.

Lives at the app root because it's a *boot hook*, not a domain. ``server.py``
calls ``boot.apply()`` once on startup. Anything domain-specific that needs
to run at boot belongs in that domain — and is invoked from here.
"""

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
    return Path(__file__).resolve().parent / "alembic.ini"


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
        from domains.spaces.assets import repository as assets_repo  # noqa: PLC0415

        bf_assets.register_asset_db_listener(assets_repo.on_asset_event)
    except Exception as exc:
        print(f"[boot] pipeline hooks skipped: {exc}")


def _run_deferred_maintenance() -> None:
    """Filesystem-heavy maintenance — must not block listening on the HTTP port."""
    t0 = time.monotonic()
    logger.info("boot: deferred maintenance starting")
    try:
        try:
            from domains.boards import palette as _wpl  # noqa: PLC0415

            _wpl.migrate_palette_from_disk_all_boards()
        except Exception as exc:
            print(f"[boot] workspace DB migration helpers skipped: {exc}")
    finally:
        logger.info(
            "boot: deferred maintenance finished in %.2fs",
            time.monotonic() - t0,
        )


def apply() -> None:
    """Idempotent: Alembic upgrade + post-upgrade hooks."""
    t_alembic = time.monotonic()
    logger.info("boot: Alembic upgrade → head")
    upgrade_schema_to_head()
    logger.info("boot: Alembic finished in %.2fs", time.monotonic() - t_alembic)

    register_pipeline_hooks()

    # Disk migrations (palette, etc.) run in a daemon thread so uvicorn can accept
    # connections immediately — avoiding "browser spins forever".
    if os.environ.get("BOARDFACTORY_SYNC_DEFERRED_BOOTSTRAP", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        _run_deferred_maintenance()
    else:
        threading.Thread(
            target=_run_deferred_maintenance,
            name="bf-deferred-boot",
            daemon=True,
        ).start()

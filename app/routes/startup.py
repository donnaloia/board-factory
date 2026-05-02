"""Post-migration filesystem cleanup run once at app startup."""

from __future__ import annotations

from boardfactory import assets as bf_assets
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config

from routes import deps
from services import board_definition as svc_bd
from storage.fs import workspace as fs_ws


def migrate_legacy_workspace_trees() -> None:
    """Seed live/history from legacy CLI dirs when present, then purge legacy trees."""
    for info in bf_boards.list_boards():
        if svc_bd.load_catalog_dict(info.id) is None:
            continue
        if not fs_ws.legacy_cli_workspace_trees_exist(info.id):
            continue
        try:
            with bf_config.scope_board(info.id):
                catalog = deps.load_board_catalog(info.id)
                seed_count = 0
                seed_failures: list[str] = []
                ids: list[tuple[str, str]] = []
                for d in catalog.get("board_spaces", {}).get("designs", []):
                    ids.append(("spaces", d["id"]))
                for p in catalog.get("feature_panels", {}).get("panels", []):
                    ids.append(("panels", p["id"]))
                ids.append(("centerpiece", "centerpiece"))

                for cat, aid in ids:
                    try:
                        result = bf_assets.seed_from_legacy_approved(cat, aid)
                        if result is not None:
                            seed_count += 1
                    except Exception as e:
                        seed_failures.append(f"{cat}/{aid}: {e}")

                if seed_failures:
                    print(
                        f"[migrate] board={info.id} "
                        f"seeded={seed_count} but skipped purge "
                        f"due to {len(seed_failures)} seed failure(s)"
                    )
                    for f in seed_failures[:5]:
                        print(f"[migrate]   FAIL: {f}")
                    continue

                removed = bf_assets.purge_legacy_dirs()
                if seed_count or removed:
                    print(
                        f"[migrate] board={info.id} "
                        f"seeded={seed_count} purged={','.join(removed) or '(none)'}"
                    )
        except Exception as e:
            print(f"[migrate] board={info.id} ERROR: {e}")

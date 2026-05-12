"""Stage 2 — wire live stills from ``BoardStore`` into bundle paths (§9.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from infrastructure.board_store import StoreFileNotFound
from infrastructure.files import workspace as fs_ws

from exporter.state import BoardExportState


def _catalog_asset_key(space: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(category, asset_id)`` for ``live_rel``, or ``None``."""
    ref = space.get("catalog_ref")
    if not isinstance(ref, dict):
        return None
    kind = ref.get("kind")
    if kind == "board_space_design":
        did = ref.get("design_id")
        return ("spaces", did) if isinstance(did, str) else None
    if kind == "feature_panel":
        pid = ref.get("panel_id")
        return ("panels", pid) if isinstance(pid, str) else None
    if kind == "centerpiece":
        return ("centerpiece", "centerpiece")
    return None


def _bundle_still_relpath(bundle_assets_root: str, asset_key: str) -> str:
    return f"{bundle_assets_root}/spaces/{asset_key}/live.png"


def stage_asset_wiring(state: BoardExportState) -> None:
    """Resolve promoted ``workspace/live/…`` PNGs via ``BoardStore``.

    * If ``options.store`` is ``None``, this stage is a **no-op** (geometry
      placeholders remain).
    * Otherwise each ``spaces[].assets.still`` is set to the bundle-relative
      path (under ``bundle_assets_root``) when the live file **exists**, or
      ``null`` when it does not.
    * If ``options.bundle_root`` is set, live bytes are **copied** into
      ``bundle_root / <relpath>`` so the tree matches ``project.json``.

    ``assets.animation`` is left unchanged (no animation files on disk yet).
    """
    store = state.options.store
    if store is None:
        return

    spaces = state.project.get("spaces")
    if not isinstance(spaces, list):
        return

    bundle_root = state.options.bundle_root
    root = str(state.project.get("bundle_assets_root") or "assets").strip("/") or "assets"
    bid = state.board_id

    for space in spaces:
        if not isinstance(space, dict):
            continue
        keys = _catalog_asset_key(space)
        assets = space.get("assets")
        if not isinstance(assets, dict):
            continue
        if keys is None:
            state.errors.append(f"assets: unknown catalog_ref on space {space.get('id')!r}")
            continue
        category, asset_id = keys
        try:
            rel = fs_ws.live_rel(category, asset_id)
        except (TypeError, ValueError) as e:
            state.errors.append(f"assets: live_rel({category!r}, {asset_id!r}): {e}")
            continue

        asset_key = "centerpiece" if category == "centerpiece" else asset_id
        relp = _bundle_still_relpath(root, asset_key)

        if not store.exists(bid, rel):
            assets["still"] = None
            continue

        if bundle_root is not None:
            dest = bundle_root / relp
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(store.read_bytes(bid, rel))
            except (OSError, StoreFileNotFound) as e:
                state.errors.append(f"assets: copy {rel} → {dest}: {e}")
                assets["still"] = None
                continue

        assets["still"] = relp.replace("\\", "/")

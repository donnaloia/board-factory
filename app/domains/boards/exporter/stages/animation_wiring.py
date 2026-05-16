"""Stage 3b — wire committed space animations into ``spaces[].assets.animation``."""

from __future__ import annotations

from typing import Any

from infrastructure.board_store import StoreFileNotFound
from space_animations.schemas.manifest import ProposalManifest

from domains.spaces.animations import repository as anim_repo
from domains.boards.exporter.stages.assets import _catalog_asset_key
from domains.boards.exporter.state import BoardExportState


def _bundle_animation_relpath(bundle_assets_root: str, asset_key: str, encoding: str) -> str:
    ext = "apng" if (encoding or "").strip().lower() == "apng" else "gif"
    return f"{bundle_assets_root}/spaces/{asset_key}/animation_live.{ext}"


def _animation_prompt_from_manifest(
    store: Any,
    board_id: str,
    manifest_rel: str | None,
) -> str:
    if not manifest_rel:
        return ""
    if not store.exists(board_id, manifest_rel):
        return ""
    try:
        raw = store.read_bytes(board_id, manifest_rel)
        manifest = ProposalManifest.model_validate_json(raw)
    except Exception:
        return ""
    return (manifest.params.animation_prompt or "").strip()


def _animation_export_payload(
    *,
    record: Any,
    bundle_relpath: str,
    animation_prompt: str,
) -> dict[str, Any]:
    return {
        "path": bundle_relpath.replace("\\", "/"),
        "encoding": record.encoding,
        "fps": record.fps,
        "duration_ms": record.duration_ms,
        "frame_count": record.frame_count,
        "loop_strategy": record.loop_strategy,
        "provider": record.provider,
        "model_id": record.model_id,
        "sha256": record.sha256,
        "animation_prompt": animation_prompt,
        "notes": record.notes or "",
    }


def stage_animation_wiring(state: BoardExportState) -> None:
    """Copy live animation clips into the bundle and fill ``assets.animation``.

    * If ``options.store`` is ``None``, this stage is a **no-op** (geometry
      leaves ``animation: null``).
    * Only **functional** panels with a committed ``space_animations`` row
      are considered (MVP: perimeter / centerpiece do not animate).
    * When ``options.bundle_root`` is set, bytes are copied from the board
      store at ``record.rel_path`` into ``assets/spaces/<panel>/animation_live.<ext>``.
    * ``animation_prompt`` is read from the committed proposal manifest on
      disk when ``proposal_manifest_rel_path`` is present.
    """
    store = state.options.store
    if store is None:
        return

    spaces = state.project.get("spaces")
    if not isinstance(spaces, list):
        return

    by_panel = anim_repo.live_animations_by_panel_slug(state.board_id)
    if not by_panel:
        return

    bundle_root = state.options.bundle_root
    root = str(state.project.get("bundle_assets_root") or "assets").strip("/") or "assets"
    bid = state.board_id

    for space in spaces:
        if not isinstance(space, dict):
            continue
        if space.get("role") != "functional":
            continue
        keys = _catalog_asset_key(space)
        if keys is None or keys[0] != "panels":
            continue
        _category, panel_slug = keys
        record = by_panel.get(panel_slug)
        if record is None:
            continue

        assets = space.get("assets")
        if not isinstance(assets, dict):
            continue

        rel_path = (record.rel_path or "").strip()
        if not rel_path:
            state.errors.append(
                f"animation: space {space.get('id')!r} row missing rel_path"
            )
            continue
        if not store.exists(bid, rel_path):
            state.errors.append(
                f"animation: missing file {rel_path!r} for panel {panel_slug!r}"
            )
            assets["animation"] = None
            continue

        asset_key = panel_slug
        bundle_relp = _bundle_animation_relpath(root, asset_key, record.encoding)

        if bundle_root is not None:
            dest = bundle_root / bundle_relp
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(store.read_bytes(bid, rel_path))
            except (OSError, StoreFileNotFound) as e:
                state.errors.append(
                    f"animation: copy {rel_path} → {dest}: {e}"
                )
                assets["animation"] = None
                continue

        prompt = _animation_prompt_from_manifest(
            store, bid, record.proposal_manifest_rel_path
        )
        assets["animation"] = _animation_export_payload(
            record=record,
            bundle_relpath=bundle_relp,
            animation_prompt=prompt,
        )

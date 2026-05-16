"""Cell-level use cases.

Read-side helpers used by the board view: per-cell status, missing-id
calculators, the batched ``BoardCellStats`` aggregate, and the cell
**side panel** payload (``build_cell_side_panel_payload``) — the
JSON shape ``side-panel.js`` consumes when the user clicks any cell on
the board.

Categories used throughout the codebase: ``"spaces"``, ``"panels"``,
``"centerpiece"``. The centerpiece is a single cell with the fixed
``asset_id == "centerpiece"``.

Per ``.cursorrules`` "service shape" — ``build_cell_side_panel_payload``
reads top-to-bottom as a chain of named ``_resolve_*`` / ``_build_*``
helpers so the high-level flow (spec → history → live → prompts →
perimeter triggers → frame → animation → assemble) is visible at a
glance.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select

from boardfactory import config as bf_config
from boardfactory import frames as bf_frames

from domains.spaces.assets import repository as asset_index
from domains.spaces.assets import services as asset_urls
from domains.spaces.assets.models import AssetVersionRecord
from domains.spaces import repository as spaces_repo
from domains.spaces.models import CellRecord
from domains.spaces.status import CellStatus
from infrastructure import board_store as bs
from infrastructure import deps
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from domains.boards import pipeline_jobs


# ────────────────────────── status / readiness ──────────────────────────


def has_generated_asset(board_id: str, category: str, asset_id: str) -> bool:
    """Truthy when the cell has a live PNG."""
    return bs.get_store().exists(board_id, fs_ws.live_rel(category, asset_id))


def missing_space_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        d["id"]
        for d in catalog.get("board_spaces", {}).get("designs", [])
        if not has_generated_asset(board_id, "spaces", d["id"])
    ]


def missing_panel_ids(board_id: str, catalog: dict) -> list[str]:
    return [
        p["id"]
        for p in catalog.get("feature_panels", {}).get("panels", [])
        if not has_generated_asset(board_id, "panels", p["id"])
    ]


# ────────────────────────── one-cell status ──────────────────────────


def cell_status(board_id: str, category: str, asset_id: str) -> CellStatus:
    """Status for one cell — live PNG presence, history count, asset URL."""
    store = bs.get_store()
    live_rel = fs_ws.live_rel(category, asset_id)
    is_live = store.exists(board_id, live_rel)

    history_pngs = fs_ws.list_history_pngs(board_id, category, asset_id)
    fs_count = len(history_pngs)
    db_count = asset_index.count_for_cell(board_id, category, asset_id)
    history_count = db_count if db_count > 0 else fs_count

    live_url = None
    if is_live:
        # Strip the leading "workspace/" so it matches the ``/.../asset/<rel>`` route.
        # full milliseconds — see ``services.asset_urls``.
        rel = live_rel.removeprefix("workspace/")
        bpath = deps.board_http_prefix(board_id)
        live_url = asset_urls.board_asset_url(
            http_prefix=bpath,
            asset_relpath=rel,
            mtime_ms=store.stat(board_id, live_rel).mtime_ms,
        )

    return CellStatus(
        asset_id=asset_id,
        category=category,
        candidates=history_count,
        approved=is_live,
        approved_url=live_url,
    )


# ────────────────────────── batched stats for the board view ──────────────────────────


@dataclass(frozen=True)
class BoardCellStats:
    """Aggregate counts the board template needs."""

    space_status: dict[str, CellStatus]
    panel_status: dict[str, CellStatus]
    centerpiece_status: CellStatus

    designs_total: int
    panels_total: int
    designs_done: int
    panels_done: int
    missing_space_ids: list[str]
    missing_panel_ids: list[str]


def collect_board_stats(board_id: str, catalog: dict) -> BoardCellStats:
    designs = catalog.get("board_spaces", {}).get("designs", [])
    panels = catalog.get("feature_panels", {}).get("panels", [])

    space_status = {d["id"]: cell_status(board_id, "spaces", d["id"]) for d in designs}
    panel_status = {p["id"]: cell_status(board_id, "panels", p["id"]) for p in panels}
    cp_status = cell_status(board_id, "centerpiece", "centerpiece")

    return BoardCellStats(
        space_status=space_status,
        panel_status=panel_status,
        centerpiece_status=cp_status,
        designs_total=len(designs),
        panels_total=len(panels),
        designs_done=sum(1 for s in space_status.values() if s.approved),
        panels_done=sum(1 for s in panel_status.values() if s.approved),
        missing_space_ids=missing_space_ids(board_id, catalog),
        missing_panel_ids=missing_panel_ids(board_id, catalog),
    )


# ────────────────────────── side-panel payload (chain) ──────────────────────────


def build_cell_side_panel_payload(
    board_id: str,
    category: str,
    asset_id: str,
    *,
    request: Request | None = None,
) -> dict:
    """JSON state for one cell: spec + live url + history list (with prompts).

    ``request`` is optional so existing tests can keep calling the
    positional 3-arg form. When provided, it lets us inspect
    ``request.state.user`` (set by ``AuthMiddleware``) to surface
    per-user provider connection state — currently used by the side
    panel's animation section to decide whether the Animate action is
    enabled.

    Reads top-to-bottom: each ``_resolve_*`` / ``_build_*`` step pulls
    one slice of the picture so the high-level flow stays readable.
    """
    catalog = deps.load_board_catalog(board_id)
    bpath = deps.board_http_prefix(board_id)

    spec = _resolve_cell_spec(catalog, category, asset_id)
    history = _list_cell_history(board_id, category, asset_id, bpath)
    live_url, has_live = _resolve_live_image(board_id, category, asset_id, bpath)

    cell_row, active_prompt, live_history_filename, live_asset_version_id = (
        _resolve_cell_state(board_id, category, asset_id, spec)
    )

    perimeter = _resolve_perimeter_meta(
        board_id=board_id, category=category, spec=spec, cell_row=cell_row
    )
    space_design_ids = _list_space_design_ids(catalog, category)

    frame_locked, frame_url, frame_payload = _resolve_frame_section(
        catalog=catalog,
        board_id=board_id,
        category=category,
        asset_id=asset_id,
        spec=spec,
        bpath=bpath,
        has_live=has_live,
    )

    animation_block = _build_animation_block(
        request=request,
        board_id=board_id,
        bpath=bpath,
        cell_row=cell_row,
        category=category,
    )

    catalog_prompt = spec.get("prompt", "") or ""
    return {
        "board_id": board_id,
        "category": category,
        "asset_id": asset_id,
        "spec": spec,
        "space_design_ids": space_design_ids,
        "functional_targets": perimeter["functional_targets"],
        "triggers_functional_cell_id": perimeter["triggers_functional_cell_id"],
        "triggers_functional": perimeter["triggers_functional"],
        "live_url": live_url,
        "has_live": has_live,
        "history": history,
        "catalog_prompt": catalog_prompt,
        "active_prompt": active_prompt,
        "live_asset_version_id": live_asset_version_id,
        "live_history_filename": live_history_filename,
        "regen_estimate_usd": pipeline_jobs.estimate_regen_one(category, asset_id),
        "candidates_per_regen": deps.candidates_per_regen_count(category),
        "frame_locked": frame_locked,
        "frame_url": frame_url,
        "frame": frame_payload,
        "animation": animation_block,
    }


# ─── step 1: spec from the catalog ───────────────────────────────────────────


def _resolve_cell_spec(catalog: dict, category: str, asset_id: str) -> dict:
    """Pluck the per-cell spec dict (id/title/prompt/uses/size/kind) out of
    the catalog. Raises ``HTTPException(404)`` for an unknown id and
    ``HTTPException(400)`` for an unknown category — matches what the API
    already returned before the split.
    """
    if category == "spaces":
        designs = catalog.get("board_spaces", {}).get("designs", [])
        d = next((x for x in designs if x["id"] == asset_id), None)
        if d is None:
            raise HTTPException(404, f"Unknown space design: {asset_id}")
        from domains.spaces.geometry import resolve_position

        layout = catalog["board_spaces"]["layout"]
        sample_pos = d["positions"][0] if d.get("positions") else None
        size = None
        if sample_pos:
            _x, _y, w, h = resolve_position(layout, sample_pos)
            size = [w, h]
        return {
            "id": d["id"],
            "title": d["id"].replace("_", " "),
            "prompt": d.get("prompt", ""),
            "uses": len(d.get("positions", [])),
            "size": size,
            "kind": "perimeter",
            "space_kind": d.get("space_kind") or "standard",
        }
    if category == "panels":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == asset_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel: {asset_id}")
        return {
            "id": p["id"],
            "title": p["id"].replace("_", " "),
            "prompt": p.get("prompt", ""),
            "uses": 1,
            "size": list(p["target_size"]),
            "kind": "functional",
        }
    if category == "centerpiece":
        cp = catalog["centerpiece"]
        return {
            "id": "centerpiece",
            "title": "Centerpiece",
            "prompt": cp.get("prompt", ""),
            "uses": 1,
            "size": list(cp["target_size"]),
            "kind": "centerpiece",
        }
    raise HTTPException(400, f"Unknown category {category}")


# ─── step 2: history listing ─────────────────────────────────────────────────


def _list_cell_history(
    board_id: str, category: str, asset_id: str, bpath: str
) -> list[dict]:
    """Hydrated history entries for the side panel timeline.

    Read-only — we set the thread-local active board without taking the
    per-board write lock. Otherwise this fetch would block on any
    in-flight pipeline job for the same board, freezing the side panel
    while a single space generates.
    """
    with bf_config.set_active_board(board_id):
        from boardfactory import assets as bf_assets

        entries = bf_assets.list_history(category, asset_id)

    return [
        {
            "filename": e.filename,
            "ts_ms": e.timestamp_ms,
            "seq": e.seq,
            "is_live": e.is_live,
            "operation": e.operation,
            "prompt": e.prompt,
            "url": f"{bpath}/asset/history/{category}/{asset_id}/{e.filename}",
        }
        for e in entries
    ]


# ─── step 3: live PNG url + presence ─────────────────────────────────────────


def _resolve_live_image(
    board_id: str, category: str, asset_id: str, bpath: str
) -> tuple[str | None, bool]:
    """Return ``(live_url, has_live)`` for the cell's committed static art."""
    live_rel = fs_ws.live_rel(category, asset_id)
    store = bs.get_store()
    has_live = store.exists(board_id, live_rel)
    if not has_live:
        return None, False
    return (
        asset_urls.board_asset_url(
            http_prefix=bpath,
            asset_relpath=live_rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, live_rel).mtime_ms,
        ),
        True,
    )


# ─── step 4: cell row + active prompt resolution ─────────────────────────────


def _resolve_cell_state(
    board_id: str,
    category: str,
    asset_id: str,
    spec: dict,
) -> tuple[CellRecord | None, str | None, str | None, int | None]:
    """Look up the ``CellRecord`` and resolve ``active_prompt``.

    Returns ``(cell_row, active_prompt, live_history_filename,
    live_asset_version_id)``.

    Resolution order for ``active_prompt``:
      1. merged prompt for the live ``AssetVersionRecord`` (DB FK win)
      2. the cell's own ``prompt`` column (free-form override)
      3. the catalog spec's prompt (template default)
    """
    catalog_prompt = spec.get("prompt", "") or ""
    cell_kind = spaces_repo.category_to_kind(category)
    if cell_kind is None:
        return None, catalog_prompt, None, None

    live_asset_version_id: int | None = None
    live_history_filename: str | None = None
    active_prompt: str | None = None
    with session_scope() as session:
        cell_row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == cell_kind,
                CellRecord.slug == asset_id,
            )
        )
        if cell_row is not None and cell_row.live_asset_version_id is not None:
            live_asset_version_id = cell_row.live_asset_version_id
            av = session.get(AssetVersionRecord, cell_row.live_asset_version_id)
            if av is not None:
                live_history_filename = av.basename
                active_prompt = asset_index.merged_prompt_for_live_asset_row(
                    board_id, category, asset_id, av
                )

    if (active_prompt is None or not str(active_prompt).strip()) and cell_row is not None:
        cell_p = (cell_row.prompt or "").strip()
        if cell_p:
            active_prompt = cell_p

    if active_prompt is None or not str(active_prompt).strip():
        active_prompt = catalog_prompt
    return cell_row, active_prompt, live_history_filename, live_asset_version_id


# ─── step 5: perimeter-only triggers + design id list ────────────────────────


def _resolve_perimeter_meta(
    *,
    board_id: str,
    category: str,
    spec: dict,
    cell_row: CellRecord | None,
) -> dict:
    """Fields the side panel's "Triggers" widget needs (perimeter spaces only).

    For non-``spaces`` categories every key is empty/``None`` — the JS
    reads them unconditionally so we always emit the same shape.

    Side effect: when the cell row carries a ``space_kind`` it overrides
    the catalog default on ``spec`` (in place). The cell row is the
    source of truth once the user has reclassified the space.
    """
    out: dict = {
        "functional_targets": [],
        "triggers_functional": None,
        "triggers_functional_cell_id": None,
    }
    if category != "spaces":
        return out

    out["functional_targets"] = [
        {
            "cell_id": c.id,
            "id": c.slug,
            "title": c.slug.replace("_", " "),
        }
        for c in spaces_repo.list_panel_cells_for_board(board_id)
    ]
    if cell_row is None:
        return out

    out["triggers_functional_cell_id"] = cell_row.triggers_functional_cell_id
    if cell_row.space_kind:
        spec["space_kind"] = cell_row.space_kind
    if not cell_row.triggers_functional_cell_id:
        return out

    with session_scope() as session:
        tgt = session.get(CellRecord, cell_row.triggers_functional_cell_id)
        if tgt is not None and tgt.board_uuid == board_id and tgt.kind == "functional":
            out["triggers_functional"] = {
                "cell_id": tgt.id,
                "id": tgt.slug,
                "title": tgt.slug.replace("_", " "),
            }
    return out


def _list_space_design_ids(catalog: dict, category: str) -> list[str]:
    """The "switch to another perimeter space" picker only needs ids."""
    if category != "spaces":
        return []
    return sorted({d["id"] for d in catalog.get("board_spaces", {}).get("designs", [])})


# ─── step 6: house-frame application + panel/mockup picker ───────────────────


def _resolve_frame_section(
    *,
    catalog: dict,
    board_id: str,
    category: str,
    asset_id: str,
    spec: dict,
    bpath: str,
    has_live: bool,
) -> tuple[bool, str | None, dict | None]:
    """Return ``(frame_locked, frame_url, frame_payload)`` for the panel cell.

    ``frame_locked`` is true iff the catalog has frame application
    enabled for panels, the house has adopted a frame asset, AND the
    cell already has a live PNG to overlay it on. ``frame_payload``
    is ``None`` for non-panel categories — those cells don't expose
    the Frame Atelier widget.
    """
    frame_block = catalog.get("frame", {}) or {}
    frame_enabled_for_cell = (
        category == "panels"
        and bool(frame_block.get("enabled"))
        and bool(frame_block.get("apply_to_panels", True))
    )
    with bf_config.set_active_board(board_id):
        frame_present = bf_frames.has_house_frame()
        frame_meta = bf_frames.read_house_meta() if frame_present else None
    frame_locked = frame_enabled_for_cell and frame_present and has_live

    if category != "panels":
        frame_url = None
        if frame_locked and spec.get("size"):
            frame_url = f"{bpath}/frame.png?w={spec['size'][0]}&h={spec['size'][1]}"
        return frame_locked, frame_url, None

    panel_sources = _collect_panel_frame_sources(catalog, board_id, asset_id, bpath)
    mockup_source = _build_frame_mockup_source(catalog, board_id, asset_id, spec, bpath)

    default_ring = max(4, min(spec["size"][0], spec["size"][1]) // 16)
    max_ring = max(default_ring, min(spec["size"][0], spec["size"][1]) // 3)

    frame_payload = {
        "supported": True,
        "enabled": bool(frame_block.get("enabled")),
        "adopted": frame_present,
        "adopted_meta": frame_meta.to_dict() if frame_meta else None,
        "applied_to_this_cell": frame_locked,
        "panel_sources": panel_sources,
        "mockup_source": mockup_source,
        "default_ring_px": default_ring,
        "min_ring_px": 2,
        "max_ring_px": max_ring,
        "preview_endpoint": f"{bpath}/api/frame/preview.png",
        "adopt_endpoint": f"{bpath}/api/frame/adopt",
        "disable_endpoint": f"{bpath}/api/frame/disable",
    }
    frame_url = (
        f"{bpath}/frame.png?w={spec['size'][0]}&h={spec['size'][1]}"
        if frame_locked and spec.get("size")
        else None
    )
    return frame_locked, frame_url, frame_payload


def _collect_panel_frame_sources(
    catalog: dict, board_id: str, asset_id: str, bpath: str
) -> list[dict]:
    """Live panel PNGs the user can pick as a "ring source" for frame adoption."""
    store = bs.get_store()
    out: list[dict] = []
    for p in catalog.get("feature_panels", {}).get("panels", []):
        prel = fs_ws.live_rel("panels", p["id"])
        if not store.exists(board_id, prel):
            continue
        out.append(
            {
                "id": p["id"],
                "label": p["id"].replace("_", " "),
                "size": list(p["target_size"]),
                "url": asset_urls.board_asset_url(
                    http_prefix=bpath,
                    asset_relpath=prel.removeprefix("workspace/"),
                    mtime_ms=store.stat(board_id, prel).mtime_ms,
                ),
                "is_self": p["id"] == asset_id,
            }
        )
    return out


def _build_frame_mockup_source(
    catalog: dict, board_id: str, asset_id: str, spec: dict, bpath: str
) -> dict | None:
    """The mockup-derived "ring source" — only available when the user has
    uploaded a board mockup. Returns ``None`` if the file is missing.
    """
    ref_rel = (catalog.get("style") or {}).get("reference_image", "mockup/board.png")
    mockup_path = fs_ws.board_root(board_id) / ref_rel
    if not mockup_path.exists():
        return None
    return {
        "id": asset_id,
        "label": f"{asset_id.replace('_', ' ')} (from mockup)",
        "size": spec["size"],
        "url": (
            f"{bpath}/api/frame/preview.png"
            f"?source_kind=mockup&source_id={asset_id}"
            f"&ring_px=8&w={spec['size'][0]}&h={spec['size'][1]}"
        ),
    }


# ─── step 7: animation block (gpt-image-2 + morph) ───────────────────────────


def _build_animation_block(
    *,
    request: Request | None,
    board_id: str,
    bpath: str,
    cell_row: CellRecord | None,
    category: str,
) -> dict:
    """Power the cell side panel's "Animation" section.

    Returns the same shape regardless of cell kind so the JS can branch
    on a single boolean (``supported``) instead of probing keys. When the
    cell is not animatable (kind, or no live static art committed) the
    section is hidden client-side; the static fields here still describe
    *why* so the action button can show a tooltip.
    """
    from domains.spaces.animations import services as anim_services
    from space_animations import config as anim_config

    supported = cell_row is not None and cell_row.kind == "functional"
    has_live_static = bool(cell_row and cell_row.live_asset_version_id)

    user = getattr(request.state, "user", None) if request is not None else None
    openai_connected = bool(user and getattr(user, "openai_api_key", "").strip())

    provider_name = anim_config.provider_name()
    needs_key = provider_name not in ("mock", "fake", "offline")
    provider_ready = (not needs_key) or openai_connected

    live = (
        anim_services.live_animation_payload(board_id, cell_row.id, bpath)
        if cell_row is not None
        else None
    )

    return {
        "supported": supported,
        "kind": cell_row.kind if cell_row is not None else None,
        "has_live_static": has_live_static,
        "provider": provider_name,
        "provider_ready": provider_ready,
        "openai_connected": openai_connected,
        "estimate_usd": anim_services.estimate_animation_cost_usd() if supported else 0.0,
        "candidates": anim_config.candidates(),
        "fps": anim_config.target_fps(),
        "duration_ms": anim_config.target_duration_ms(),
        "encoding": anim_config.default_encoding(),
        "loop_strategy": anim_config.default_loop_strategy(),
        "animate_endpoint": (
            f"{bpath}/api/cell/{category}/{cell_row.slug}/animate"
            if cell_row is not None and supported
            else None
        ),
        "proposals_url_template": (
            f"{bpath}/api/cell/{category}/{cell_row.slug}/animations/proposals/{{job_id}}"
            if cell_row is not None and supported
            else None
        ),
        "commit_url_template": (
            f"{bpath}/api/cell/{category}/{cell_row.slug}"
            f"/animations/proposals/{{job_id}}/commit"
            if cell_row is not None and supported
            else None
        ),
        "live": live,
    }

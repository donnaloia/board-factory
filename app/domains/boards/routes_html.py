"""Board HTML pages — Jinja templates under ``/users/.../board-games/...``."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from jobs import cost_ledger, pipeline_adapters
from frontend.views import spec_data
from frontend.views.board_svg import render_board_svg, render_spec_svg
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames

from domains.boards.routes_common import NestedBoardId, board_prefix
from infrastructure import deps
from domains.boards import services as svc_boards
from domains.cells import services as svc_cells
from assets import services as asset_urls
from infrastructure import board_store as bs
from infrastructure.files import workspace as fs_ws

router = APIRouter()


@router.get("/users/{username}/board-games/{path_slug}/", response_class=HTMLResponse)
def board_view(request: Request, board_id: NestedBoardId):
    if not fs_ws.has_palette(board_id):
        return RedirectResponse(f"{board_prefix(board_id)}/setup", status_code=303)

    catalog = deps.load_board_catalog(board_id)
    stats = svc_cells.collect_board_stats(board_id, catalog)
    space_status = stats.space_status
    panel_status = stats.panel_status
    cp_status = stats.centerpiece_status
    n_designs = stats.designs_total
    n_panels = stats.panels_total
    designs_done = stats.designs_done
    panels_done = stats.panels_done
    missing_space_ids = stats.missing_space_ids
    missing_panel_ids = stats.missing_panel_ids
    n_missing_designs = len(missing_space_ids)
    n_missing_panels = len(missing_panel_ids)
    generated_designs = n_designs - n_missing_designs

    designs_list = catalog.get("board_spaces", {}).get("designs", [])
    total_positions = sum(len(d.get("positions", [])) for d in designs_list)
    missing_positions = sum(
        len(d.get("positions", [])) for d in designs_list
        if d["id"] in missing_space_ids
    )
    generated_positions = total_positions - missing_positions

    all_generate_estimate = pipeline_adapters.estimate_generate_all(
        n_missing_designs, n_missing_panels
    )
    n_missing_all = n_missing_designs + n_missing_panels
    n_generated_all = generated_designs + (n_panels - n_missing_panels)

    frame_overlay_url = None
    frame_block = catalog.get("frame", {}) or {}
    frame_meta = None
    frame_adopted = False
    with bf_config.set_active_board(board_id):
        if bf_frames.has_house_frame():
            frame_adopted = True
            frame_meta = bf_frames.read_house_meta()
            if frame_block.get("enabled") and frame_block.get("apply_to_panels", True):
                frame_overlay_url = f"{board_prefix(board_id)}/frame.png"

    frame_status = {
        "adopted": frame_adopted,
        "enabled": bool(frame_block.get("enabled")),
        "source_kind": frame_meta.source_kind if frame_meta else None,
        "source_id": frame_meta.source_id if frame_meta else None,
        "ring_px": frame_meta.ring_px if frame_meta else None,
    }

    svg_markup = render_board_svg(
        catalog, space_status, panel_status, cp_status,
        frame_overlay_url=frame_overlay_url,
    )

    user = getattr(request.state, "user", None)
    has_openai_key = bool(
        (user and user.openai_api_key)
        or os.environ.get("OPENAI_API_KEY", "")
    )

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "board_size": catalog["board_size"],
        "svg_markup": svg_markup,
        "has_openai_key": has_openai_key,
        "analyze_cost": pipeline_adapters.ANALYZE_COST_USD,
        "stats": {
            "designs_total": n_designs,
            "designs_done": designs_done,
            "panels_total": n_panels,
            "panels_done": panels_done,
            "centerpiece_done": cp_status.approved,
        },
        "all_generation": {
            "missing": n_missing_all,
            "generated": n_generated_all,
            "total": n_designs + n_panels,
            "missing_spaces": n_missing_designs,
            "missing_panels": n_missing_panels,
            "estimate": all_generate_estimate,
            "label": (
                "All assets generated" if n_missing_all == 0
                else "Generate all spaces & UI" if n_generated_all == 0
                else "Generate missing spaces"
            ),
        },
        "frame_status": frame_status,
        "generation": svc_boards.read_generation(catalog),
    })
    return request.app.state.templates.TemplateResponse(request, "board.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/setup", response_class=HTMLResponse)
def setup_view(request: Request, board_id: NestedBoardId):
    mockup_present, mockup_rel = svc_boards.mockup_present(board_id)
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "mockup_present": mockup_present,
        "mockup_rel": mockup_rel,
        "mockup_ready_hint": request.query_params.get("mockup_ready") == "1",
    })
    return request.app.state.templates.TemplateResponse(request, "setup.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/spec", response_class=HTMLResponse)
def spec_view(request: Request, board_id: NestedBoardId):
    """Live tech spec from the board's catalog + the shared prose markdown."""
    catalog = deps.load_board_catalog(board_id)
    prose = deps.load_spec_prose_sections()
    user = getattr(request.state, "user", None)
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "summary": spec_data.header_summary(catalog),
        "density": spec_data.pixel_density_rows(catalog),
        "designs": spec_data.design_table_rows(catalog),
        "panels": spec_data.panel_table_rows(catalog),
        "battles": spec_data.battle_table_rows(catalog),
        "legend": spec_data.design_summary_by_kind(catalog),
        "svg_markup": render_spec_svg(catalog),
        "prose": prose,
        "cost": cost_ledger.summary(),
        "has_palette": fs_ws.has_palette(board_id),
        "estimates": {"spaces": 0, "panels": 0, "centerpiece": 0},
        "user": user.public_dict() if user else None,
    })
    return request.app.state.templates.TemplateResponse(request, "spec.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/frame", response_class=HTMLResponse)
def frame_view(request: Request, board_id: NestedBoardId):
    """Frame Atelier — Propose / Refine / Commit + Approach D progress.

    Replaces the old single-step picker; the Jinja template renders the
    shell (status bar, phase rail, source picker grid, refine canvas
    placeholder, commit panel) and ``frame-atelier.js`` wires up the
    interactive behaviour against the new ``/api/frame/...`` endpoints.
    """
    catalog = deps.load_board_catalog(board_id)
    store = bs.get_store()
    bp = board_prefix(board_id)

    with bf_config.set_active_board(board_id):
        has_frame = bf_frames.has_house_frame()
        meta = bf_frames.read_house_meta() if has_frame else None

    # Lazy-backfill the relational row if the on-disk pack predates the
    # frame_instances table; the Atelier UI surfaces "imported from disk"
    # provenance based on the row that comes back here.
    from domains.cells import frames_repository as frames_repo

    active_view = frames_repo.ensure_active_for_disk_pack(board_id)

    # Source: live panels (ordered, with size + URL).
    panels = catalog.get("feature_panels", {}).get("panels", [])
    panel_sources: list[dict] = []
    for p in panels:
        live_rel = fs_ws.live_rel("panels", p["id"])
        size = [int(p["target_size"][0]), int(p["target_size"][1])]
        if not store.exists(board_id, live_rel):
            panel_sources.append({
                "id": p["id"], "label": p["id"].replace("_", " "),
                "size": size, "url": None, "has_live": False,
            })
            continue
        url_rel = live_rel.removeprefix("workspace/")
        panel_sources.append({
            "id": p["id"],
            "label": p["id"].replace("_", " "),
            "size": size,
            "url": asset_urls.board_asset_url(
                http_prefix=bp,
                asset_relpath=url_rel,
                mtime_ms=store.stat(board_id, live_rel).mtime_ms,
            ),
            "has_live": True,
        })

    # Source: mockup regions (one per panel bbox).
    mockup_sources: list[dict] = []
    ref_rel = (catalog.get("style") or {}).get("reference_image") or "mockup/board.png"
    if store.exists(board_id, ref_rel):
        for p in panels:
            size = [int(p["target_size"][0]), int(p["target_size"][1])]
            mockup_sources.append({
                "id": p["id"],
                "label": f"{p['id'].replace('_', ' ')} (from mockup)",
                "size": size,
                "url": (
                    f"{bp}/api/frame/preview.png"
                    f"?source_kind=mockup&source_id={p['id']}"
                    f"&ring_px=8&w={size[0]}&h={size[1]}"
                ),
            })

    user = getattr(request.state, "user", None)
    has_openai_key = bool(
        (user and user.openai_api_key)
        or os.environ.get("OPENAI_API_KEY", "")
    )

    n_panels = len(panels)
    typical_size = (
        [int(panels[0]["target_size"][0]), int(panels[0]["target_size"][1])]
        if panels else [260, 240]
    )
    default_ring = max(4, min(typical_size) // 16)
    max_ring = max(default_ring, min(typical_size) // 3)

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "has_frame": has_frame,
        "frame_enabled": bool((catalog.get("frame") or {}).get("enabled")),
        "meta": meta.to_dict() if meta else None,
        "active_view": active_view.to_dict() if active_view else None,
        "frame_url": (
            f"{bp}/frame.png?t={asset_urls.wall_clock_ms()}" if has_frame else None
        ),
        "panel_sources": panel_sources,
        "mockup_sources": mockup_sources,
        "n_panels": n_panels,
        "typical_size": typical_size,
        "default_ring_px": default_ring,
        "min_ring_px": 2,
        "max_ring_px": max_ring,
        "has_openai_key": has_openai_key,
    })
    return request.app.state.templates.TemplateResponse(request, "frame.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/preview", response_class=HTMLResponse)
def preview_view(request: Request, board_id: NestedBoardId):
    store = bs.get_store()
    preview_rel = svc_boards.composite_preview_workspace_rel(board_id)
    preview_present = preview_rel is not None
    preview_url = None
    bp = board_prefix(board_id)
    if preview_rel is not None:
        preview_url = asset_urls.board_asset_url(
            http_prefix=bp,
            asset_relpath=preview_rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, preview_rel).mtime_ms,
        )
    manifest_present = store.exists(board_id, "export/board_manifest.json")
    exported_count = sum(1 for f in store.list(board_id, "export") if f.endswith(".png"))
    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "preview_present": preview_present,
        "preview_url": preview_url,
        "manifest_present": manifest_present,
        "exported_count": exported_count,
    })
    return request.app.state.templates.TemplateResponse(request, "preview.html", ctx)


@router.get("/users/{username}/board-games/{path_slug}/device-preview", response_class=HTMLResponse)
def device_preview_view(request: Request, board_id: NestedBoardId):
    """Composited board inside device frame mockups."""
    store = bs.get_store()
    bp = board_prefix(board_id)

    def _asset_url(name: str) -> str | None:
        rel = f"workspace/preview/{name}"
        if not store.exists(board_id, rel):
            return None
        return asset_urls.board_asset_url(
            http_prefix=bp,
            asset_relpath=rel.removeprefix("workspace/"),
            mtime_ms=store.stat(board_id, rel).mtime_ms,
        )

    idle_url = _asset_url("board_idle.png")
    active_url = _asset_url("board_active.png")

    catalog = deps.load_board_catalog(board_id)
    bw, bh = catalog.get("board_size", [1920, 1080])

    ctx = deps.editorial_template_context(board_id, request)
    ctx.update({
        "idle_url": idle_url,
        "active_url": active_url,
        "preview_present": bool(idle_url or active_url),
        "board_w": bw,
        "board_h": bh,
    })
    return request.app.state.templates.TemplateResponse(request, "device_preview.html", ctx)

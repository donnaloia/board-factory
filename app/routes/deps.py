"""Shared helpers for route modules: auth guards, catalog HTTP mapping, job glue.

Path resolution uses ``storage.fs.workspace`` directly — no thin re-export
wrappers around ``board_root`` / ``workspace_dir``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import markdown as md
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import auth
import cost_ledger
import pipeline_adapters
import spec_data
from board_svg import CellStatus
from boardfactory import boards as bf_boards
from boardfactory import config as bf_config
from boardfactory import frames as bf_frames
from jobs import get_runner

from services import board_definition as bd
from services import board_ownership
from services import catalog as svc_catalog
from services import cells as svc_cells
from services import jobs as svc_jobs

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
SPEC_PROSE_PATH = REPO_ROOT / "docs" / "spec_prose.md"


def safe_next(next_path: str | None) -> str:
    """Whitelist the redirect target — only allow same-origin absolute paths."""
    if not next_path:
        return "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    if next_path.startswith("/login") or next_path.startswith("/register"):
        return "/"
    return next_path


def board_on_disk_or_404(board_id: str) -> bf_boards.BoardInfo:
    if not bf_boards.is_valid_id(board_id):
        raise HTTPException(400, "Invalid board id")
    info = bf_boards.get_board(board_id)
    if info is None:
        raise HTTPException(404, f"Unknown board {board_id!r}")
    return info


def ensure_owned_board(request: Request, board_id: str) -> bf_boards.BoardInfo:
    info = board_on_disk_or_404(board_id)
    user = auth.require_user(request)
    if not board_ownership.user_owns_board(user.id, board_id):
        raise HTTPException(404, f"Unknown board {board_id!r}")
    return info


def load_board_catalog(board_id: str) -> dict[str, Any]:
    try:
        return svc_catalog.load_catalog(board_id)
    except svc_catalog.CatalogNotFound:
        raise HTTPException(404, f"Catalog not found for board {board_id!r}")


def save_board_catalog(board_id: str, data: dict[str, Any]) -> None:
    svc_catalog.save_catalog(board_id, data)


def generation_defaults_block() -> dict:
    return svc_catalog._generation_defaults()  # type: ignore[attr-defined]


def read_generation_from_catalog(catalog: dict) -> dict:
    return svc_catalog.read_generation(catalog)


def workspace_cell_status(board_id: str, category: str, asset_id: str) -> CellStatus:
    return svc_cells.cell_status(board_id, category, asset_id)


def missing_space_ids(board_id: str, catalog: dict) -> list[str]:
    return svc_cells.missing_space_ids(board_id, catalog)


def missing_panel_ids(board_id: str, catalog: dict) -> list[str]:
    return svc_cells.missing_panel_ids(board_id, catalog)


def resolved_live_asset_path(board_id: str, category: str, asset_id: str) -> Path:
    from services import asset_live

    return asset_live.resolved_live_path(board_id, category, asset_id)


def workspace_file_or_404(board_id: str, rel: str) -> Path:
    from storage.fs import workspace as fs_ws

    try:
        return fs_ws.safe_workspace_relative(board_id, rel)
    except fs_ws.PathTraversalError:
        raise HTTPException(400, "Invalid path")


def has_board_palette(board_id: str) -> bool:
    from storage.fs import workspace as fs_ws

    return fs_ws.has_palette(board_id)


def mockup_present_for_board(board_id: str) -> tuple[bool, str]:
    from services import boards as svc_boards

    return svc_boards.mockup_present(board_id)


def accepts_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept


def job_or_redirect_response(
    request: Request, job_id: str, redirect_to: str = "/",
) -> JSONResponse | RedirectResponse:
    if accepts_json(request):
        return JSONResponse({"job_id": job_id})
    return RedirectResponse(redirect_to, status_code=303)


def editorial_template_context(board_id: str | None, request: Request | None = None) -> dict:
    project = "Board Factory"
    if board_id:
        # Canonical title is ``board_games.project``. ``BoardInfo.project`` only
        # reflects legacy ``catalog.yml`` on disk or defaults to the slug.
        row = bd.load_catalog_dict(board_id)
        if row is not None:
            project = str(row.get("project") or board_id)
        else:
            info = bf_boards.get_board(board_id)
            if info:
                project = info.project
    user = getattr(request.state, "user", None) if request is not None else None
    return {
        "board_id": board_id,
        "project": project,
        "has_palette": has_board_palette(board_id) if board_id else False,
        "cost": cost_ledger.summary(),
        "estimates": pipeline_cost_estimates() if board_id
        else {"spaces": 0, "panels": 0, "centerpiece": 0, "refine": 0},
        "user": user.public_dict() if user else None,
    }


def pipeline_cost_estimates() -> dict:
    return {
        "spaces": pipeline_adapters.estimate_generate("spaces"),
        "panels": pipeline_adapters.estimate_generate("panels"),
        "centerpiece": pipeline_adapters.estimate_generate("centerpiece"),
        "refine": pipeline_adapters.estimate_refine(),
    }


def enqueue_pipeline_job(
    *, label: str, operation: str, target: str | None, cost_estimate: float, fn,
) -> str:
    return svc_jobs.enqueue(
        label=label,
        operation=operation,
        target=target,
        cost_estimate=cost_estimate,
        fn=fn,
    )


def scoped_pipeline_callable(board_id: str, fn):
    return svc_jobs.scoped(board_id, fn)


def user_provider_api_keys(request: Request) -> dict[str, str]:
    u = getattr(request.state, "user", None)
    keys: dict[str, str] = {}
    if u:
        if u.pixellab_api_key:
            keys["pixellab_key"] = u.pixellab_api_key
        if u.openai_api_key:
            keys["openai_key"] = u.openai_api_key
    return keys


def load_spec_prose_sections() -> dict[str, str]:
    if not SPEC_PROSE_PATH.exists():
        return {}
    raw = SPEC_PROSE_PATH.read_text()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is None:
            continue
        sections[current].append(line)
    return {
        slug: md.markdown("\n".join(body), extensions=["tables"])
        for slug, body in sections.items()
    }


def candidates_per_regen_count(category: str) -> int:
    if category == "spaces":
        return bf_config.SPACE_CANDIDATES
    if category == "panels":
        return bf_config.PANEL_CANDIDATES
    if category == "centerpiece":
        return bf_config.CENTERPIECE_CANDIDATES
    return 0


def build_cell_side_panel_payload(board_id: str, category: str, asset_id: str) -> dict:
    """JSON state for one cell: spec + live url + history list (with prompts)."""
    from storage.fs import workspace as fs_ws

    catalog = load_board_catalog(board_id)

    spec: dict = {}
    if category == "spaces":
        designs = catalog.get("board_spaces", {}).get("designs", [])
        d = next((x for x in designs if x["id"] == asset_id), None)
        if d is None:
            raise HTTPException(404, f"Unknown space design: {asset_id}")
        from board_svg import _resolve_position

        layout = catalog["board_spaces"]["layout"]
        sample_pos = d["positions"][0] if d.get("positions") else None
        size = None
        if sample_pos:
            _x, _y, w, h = _resolve_position(layout, sample_pos)
            size = [w, h]
        spec = {
            "id": d["id"],
            "title": d["id"].replace("_", " "),
            "prompt": d.get("prompt", ""),
            "uses": len(d.get("positions", [])),
            "size": size,
            "kind": "space",
        }
    elif category == "panels":
        panels = catalog.get("feature_panels", {}).get("panels", [])
        p = next((x for x in panels if x["id"] == asset_id), None)
        if p is None:
            raise HTTPException(404, f"Unknown panel: {asset_id}")
        spec = {
            "id": p["id"],
            "title": p["id"].replace("_", " "),
            "prompt": p.get("prompt", ""),
            "uses": 1,
            "size": list(p["target_size"]),
            "kind": "panel",
        }
    elif category == "centerpiece":
        cp = catalog["centerpiece"]
        spec = {
            "id": "centerpiece",
            "title": "Centerpiece",
            "prompt": cp.get("prompt", ""),
            "uses": 1,
            "size": list(cp["target_size"]),
            "kind": "centerpiece",
        }
    else:
        raise HTTPException(400, f"Unknown category {category}")

    with bf_config.scope_board(board_id):
        from boardfactory import assets as bf_assets

        entries = bf_assets.list_history(category, asset_id)

    history = [
        {
            "filename": e.filename,
            "ts_ms": e.timestamp_ms,
            "seq": e.seq,
            "is_live": e.is_live,
            "operation": e.operation,
            "prompt": e.prompt,
            "url": f"/b/{board_id}/asset/history/{category}/{asset_id}/{e.filename}",
        }
        for e in entries
    ]

    live = resolved_live_asset_path(board_id, category, asset_id)
    ws = fs_ws.workspace_dir(board_id)
    live_url = None
    if live.exists():
        live_url = (
            f"/b/{board_id}/asset/{live.relative_to(ws).as_posix()}"
            f"?t={int(live.stat().st_mtime)}"
        )

    catalog_prompt = spec.get("prompt", "") or ""
    active_prompt = catalog_prompt
    for e in entries:
        if not e.is_live:
            continue
        # Normal case: live row came from a regen with metadata.
        if e.prompt is not None:
            active_prompt = e.prompt
            break
        # Cleanup / refine sometimes promote with no stored prompt; newest-first
        # history still has the last generation prompt on the next row.
        for e2 in entries:
            if e2.prompt is not None:
                active_prompt = e2.prompt
                break
        break

    frame_block = catalog.get("frame", {}) or {}
    frame_enabled_for_cell = (
        category == "panels"
        and bool(frame_block.get("enabled"))
        and bool(frame_block.get("apply_to_panels", True))
    )
    with bf_config.scope_board(board_id):
        frame_present = bf_frames.has_house_frame()
        frame_meta = bf_frames.read_house_meta() if frame_present else None
    frame_locked = frame_enabled_for_cell and frame_present and live.exists()

    frame_payload: dict | None = None
    if category == "panels":
        all_panels = catalog.get("feature_panels", {}).get("panels", [])
        panel_sources: list[dict] = []
        for p in all_panels:
            p_live = resolved_live_asset_path(board_id, "panels", p["id"])
            if p_live.exists():
                panel_sources.append(
                    {
                        "id": p["id"],
                        "label": p["id"].replace("_", " "),
                        "size": list(p["target_size"]),
                        "url": (
                            f"/b/{board_id}/asset/"
                            f"{p_live.relative_to(ws).as_posix()}"
                            f"?t={int(p_live.stat().st_mtime)}"
                        ),
                        "is_self": p["id"] == asset_id,
                    }
                )

        mockup_source: dict | None = None
        ref_rel = (catalog.get("style") or {}).get("reference_image", "mockup/board.png")
        mockup_path = fs_ws.board_root(board_id) / ref_rel
        if mockup_path.exists():
            mockup_source = {
                "id": asset_id,
                "label": f"{asset_id.replace('_', ' ')} (from mockup)",
                "size": spec["size"],
                "url": (
                    f"/b/{board_id}/api/frame/preview.png"
                    f"?source_kind=mockup&source_id={asset_id}"
                    f"&ring_px=8&w={spec['size'][0]}&h={spec['size'][1]}"
                ),
            }

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
            "preview_endpoint": f"/b/{board_id}/api/frame/preview.png",
            "adopt_endpoint": f"/b/{board_id}/api/frame/adopt",
            "disable_endpoint": f"/b/{board_id}/api/frame/disable",
        }

    return {
        "board_id": board_id,
        "category": category,
        "asset_id": asset_id,
        "spec": spec,
        "live_url": live_url,
        "has_live": live.exists(),
        "history": history,
        "catalog_prompt": catalog_prompt,
        "active_prompt": active_prompt,
        "regen_estimate_usd": pipeline_adapters.estimate_regen_one(category, asset_id),
        "candidates_per_regen": candidates_per_regen_count(category),
        "frame_locked": frame_locked,
        "frame_url": (
            f"/b/{board_id}/frame.png?w={spec['size'][0]}&h={spec['size'][1]}"
            if frame_locked and spec.get("size")
            else None
        ),
        "frame": frame_payload,
    }

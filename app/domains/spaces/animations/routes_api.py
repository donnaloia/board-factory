"""HTTP routes for the space-animations slice.

Mounts under the existing nested board path so URLs read consistently with
the rest of the spaces domain:

  POST /users/{username}/board-games/{path_slug}/api/cell/{category}/{asset_id}/animate
  GET  .../api/cell/{category}/{asset_id}/animations/proposals/{job_id}
  POST .../api/cell/{category}/{asset_id}/animations/proposals/{job_id}/commit
  GET  .../api/cell/{category}/{asset_id}/animations/live
  GET  .../api/cell-animation/{cell_id}/live
  GET  .../api/cell-animation/{cell_id}/proposals/{job_id}/{filename}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from infrastructure import deps
from domains.spaces.animations import manifest_io, repository, services

router = APIRouter()

NestedBoardId = Annotated[str, Depends(deps.require_nested_board)]


# ────────────────────────── enqueue ──────────────────────────


@router.post(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell/{category}/{asset_id}/animate"
)
async def api_animate_cell(
    request: Request,
    board_id: NestedBoardId,
    category: str,
    asset_id: str,
):
    """Start a 3-candidate animation job for one cell. Returns ``{job_id}``.

    Expects JSON ``{"animation_prompt": "…"}`` describing the desired motion.

    ``async def`` is required because :func:`deps.enqueue_pipeline_job` calls
    ``asyncio.get_running_loop()`` to attach the worker task — a sync handler
    runs in a threadpool with no running loop and would raise.
    """
    from functools import partial

    from domains.spaces.animations import pipeline_jobs

    try:
        raw = await request.json()
    except Exception:
        raw = {}
    animation_prompt = str(raw.get("animation_prompt") or "").strip()
    if not animation_prompt:
        raise HTTPException(400, "Animation prompt is required.")
    if len(animation_prompt) > 2000:
        raise HTTPException(
            400, "Animation prompt is too long (max 2000 characters)."
        )

    cell_id = services.find_cell_id(board_id, category, asset_id)
    if cell_id is None:
        raise HTTPException(404, f"Unknown cell {category}/{asset_id}")
    try:
        cell = services.assert_can_animate(board_id, cell_id)
    except services.AnimationGateError as e:
        raise HTTPException(400, str(e)) from e

    label = services.build_animation_job_label(cell)
    keys = deps.user_provider_api_keys(request)
    fn = deps.scoped_pipeline_callable(
        board_id,
        partial(
            pipeline_jobs.animate_space_job,
            board_id=board_id,
            cell_id=cell_id,
            openai_key=keys.get("openai_key"),
            animation_prompt=animation_prompt,
        ),
    )
    job_id = deps.enqueue_pipeline_job(
        label=label,
        operation="animate.space",
        target=cell.slug,
        cost_estimate=services.estimate_animation_cost_usd(),
        fn=fn,
    )
    return JSONResponse({"job_id": job_id})


# ────────────────────────── list proposals ──────────────────────────


@router.get(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell/{category}/{asset_id}/animations/proposals/{job_id}"
)
def api_list_proposals(
    request: Request,
    board_id: NestedBoardId,
    category: str,
    asset_id: str,
    job_id: str,
):
    cell_id = services.find_cell_id(board_id, category, asset_id)
    if cell_id is None:
        raise HTTPException(404, f"Unknown cell {category}/{asset_id}")
    try:
        view = services.list_proposals(board_id, cell_id, job_id)
    except services.ProposalNotFound as e:
        raise HTTPException(404, str(e)) from e

    bpath = deps.board_http_prefix(board_id)
    candidates = [
        {
            "index": c.index,
            "filename": c.filename,
            "encoding": c.encoding,
            "fps": c.fps,
            "duration_ms": c.duration_ms,
            "frame_count": c.frame_count,
            "loop_strategy": c.loop_strategy,
            "sha256": c.sha256,
            "notes": c.notes,
            "url": (
                f"{bpath}/api/cell-animation/{cell_id}"
                f"/proposals/{job_id}/{c.filename}"
            ),
        }
        for c in view.candidates
    ]
    return JSONResponse(
        {
            "job_id": view.job_id,
            "cell_id": view.cell_id,
            "provider": view.provider,
            "model_id": view.model_id,
            "source_asset_version_id": view.source_asset_version_id,
            "created_ms": view.created_ms,
            "candidates": candidates,
        }
    )


# ────────────────────────── commit ──────────────────────────


class _CommitBody(BaseModel):
    proposal_index: int = Field(ge=0)


@router.post(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell/{category}/{asset_id}/animations/proposals/{job_id}/commit"
)
async def api_commit_proposal(
    request: Request,
    board_id: NestedBoardId,
    category: str,
    asset_id: str,
    job_id: str,
):
    cell_id = services.find_cell_id(board_id, category, asset_id)
    if cell_id is None:
        raise HTTPException(404, f"Unknown cell {category}/{asset_id}")
    try:
        body = _CommitBody.model_validate(await request.json())
    except Exception as e:
        raise HTTPException(400, f"Invalid commit body: {e}") from e
    try:
        record = services.commit_proposal(board_id, cell_id, job_id, body.proposal_index)
    except services.AnimationGateError as e:
        raise HTTPException(400, str(e)) from e
    except services.ProposalNotFound as e:
        raise HTTPException(404, str(e)) from e

    bpath = deps.board_http_prefix(board_id)
    return JSONResponse(
        {
            "id": record.id,
            "cell_id": record.cell_id,
            "encoding": record.encoding,
            "fps": record.fps,
            "duration_ms": record.duration_ms,
            "frame_count": record.frame_count,
            "loop_strategy": record.loop_strategy,
            "provider": record.provider,
            "model_id": record.model_id,
            "created_ms": record.created_ms,
            "url": f"{bpath}/api/cell-animation/{cell_id}/live",
        }
    )


# ────────────────────────── live metadata ──────────────────────────


@router.get(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell/{category}/{asset_id}/animations/live"
)
def api_live_animation_meta(
    request: Request,
    board_id: NestedBoardId,
    category: str,
    asset_id: str,
):
    cell_id = services.find_cell_id(board_id, category, asset_id)
    if cell_id is None:
        raise HTTPException(404, f"Unknown cell {category}/{asset_id}")
    record = repository.get_live_for_cell(cell_id)
    if record is None:
        return JSONResponse({"live": None})
    bpath = deps.board_http_prefix(board_id)
    return JSONResponse(
        {
            "live": {
                "id": record.id,
                "encoding": record.encoding,
                "fps": record.fps,
                "duration_ms": record.duration_ms,
                "frame_count": record.frame_count,
                "loop_strategy": record.loop_strategy,
                "provider": record.provider,
                "model_id": record.model_id,
                "created_ms": record.created_ms,
                "url": f"{bpath}/api/cell-animation/{cell_id}/live",
            }
        }
    )


# ────────────────────────── file serving ──────────────────────────


@router.get(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell-animation/{cell_id}/live"
)
def api_serve_live(
    request: Request,
    board_id: NestedBoardId,
    cell_id: str,
):
    record = repository.get_live_for_cell(cell_id)
    if record is None:
        raise HTTPException(404, "No live animation for this cell")
    path = manifest_io.live_path(board_id, cell_id, record.encoding)
    if not path.exists():
        raise HTTPException(404, "Live animation file missing on disk")
    return FileResponse(
        path,
        media_type=_media_type_for(record.encoding),
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/users/{username}/board-games/{path_slug}"
    "/api/cell-animation/{cell_id}/proposals/{job_id}/{filename}"
)
def api_serve_proposal(
    request: Request,
    board_id: NestedBoardId,
    cell_id: str,
    job_id: str,
    filename: str,
):
    if "/" in filename or ".." in filename or filename.startswith("."):
        raise HTTPException(400, "Invalid filename")
    path = manifest_io.proposal_file(board_id, cell_id, job_id, filename)
    if not path.exists():
        raise HTTPException(404, "Proposal file not found")
    return FileResponse(
        path,
        media_type=_media_type_from_filename(filename),
        headers={"Cache-Control": "no-store"},
    )


def _media_type_for(encoding: str) -> str:
    e = (encoding or "").strip().lower()
    if e == "apng":
        return "image/apng"
    return "image/gif"


def _media_type_from_filename(name: str) -> str:
    n = name.lower()
    if n.endswith(".apng"):
        return "image/apng"
    if n.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"

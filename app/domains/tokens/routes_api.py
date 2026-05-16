"""Token Factory JSON/binary routes — top-level domain.

URL structure:

  POST   /api/token-factory/tokens                                       create token
  GET    /api/token-factory/tokens                                       list user's tokens
  DELETE /users/{username}/token-factory/{path_slug}                     delete token
  POST   /users/{username}/token-factory/{path_slug}/api/relink-board    change/clear board link
  POST   /users/{username}/token-factory/{path_slug}/api/explore         start design_explore job
  POST   /users/{username}/token-factory/{path_slug}/api/commit-canonical lock design
  POST   /users/{username}/token-factory/{path_slug}/api/unlock          clear design lock
  POST   /users/{username}/token-factory/{path_slug}/api/clips/{clip}    start generate_clip job
  POST   /users/{username}/token-factory/{path_slug}/api/publish         start pack_publish job
  GET    /users/{username}/token-factory/{path_slug}/api/payload         full detail payload
  GET    /users/{username}/token-factory/{path_slug}/api/job/{job_id}    job status
  GET    /users/{username}/token-factory/{path_slug}/asset/{rest:path}   serve token files
"""

from __future__ import annotations

import functools
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from auth.middleware import require_user
from infrastructure import deps
from domains.tokens import services as svc_tokens
from domains.tokens import workspace as token_ws

router = APIRouter()


# ── request bodies ────────────────────────────────────────────────────────────

class CreateTokenBody(BaseModel):
    slug: str | None = None
    display_name: str = ""
    linked_board_id: str | None = None
    locomotion_profile: str = "walk"
    facing_policy: str = "flip_x"
    canvas_w: int = 96
    canvas_h: int = 128
    frame_fps: int = 12


class CommitCanonicalBody(BaseModel):
    candidate_index: int
    style_sentence: str


class RelinkBoardBody(BaseModel):
    linked_board_id: str | None = None


# ── shared helpers ────────────────────────────────────────────────────────────

def _resolve_token(request: Request, username: str, path_slug: str):
    """Resolve nested URL → ``TokenSummary``; enforce ownership.

    The logged-in user must match the URL's ``username`` AND own the token.
    """
    user = require_user(request)
    if user.username != username:
        raise HTTPException(404, "Not found")
    try:
        token = svc_tokens.get_token_by_path(user.id, path_slug)
    except svc_tokens.TokenNotFound as e:
        raise HTTPException(404, str(e)) from e
    return user, token


def _token_asset_base(username: str, path_slug: str) -> str:
    return f"/users/{username}/token-factory/{path_slug}"


def _pipeline_callable_for_token(token, fn: Callable) -> Callable:
    """Wrap ``fn`` for the job runner.

    When the token is linked to a board, use the standard board-scope wrapper
    so the per-board write lock + palette materialization still happen.
    When unlinked, just pass through — no board context to enter.
    """
    if token.linked_board_id:
        return deps.scoped_pipeline_callable(token.linked_board_id, fn)
    return lambda job, cancel: fn(job, cancel)


# ── list / create (top-level) ─────────────────────────────────────────────────

@router.get("/api/token-factory/tokens")
def api_list_tokens(request: Request):
    user = require_user(request)
    tokens = svc_tokens.list_tokens(user.id)
    return JSONResponse(
        {"tokens": [svc_tokens._summary_to_dict(t) for t in tokens]}
    )


@router.post("/api/token-factory/tokens")
def api_create_token(request: Request, body: CreateTokenBody):
    user = require_user(request)
    try:
        summary = svc_tokens.create_token(
            user_id=user.id,
            display_name=body.display_name,
            slug=body.slug,
            linked_board_id=body.linked_board_id,
            locomotion_profile=body.locomotion_profile,
            facing_policy=body.facing_policy,
            canvas_w=body.canvas_w,
            canvas_h=body.canvas_h,
            frame_fps=body.frame_fps,
        )
    except svc_tokens.TokenExists as e:
        raise HTTPException(409, str(e)) from e
    except svc_tokens.BoardAuthError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return JSONResponse({"token": svc_tokens._summary_to_dict(summary)})


# ── delete ────────────────────────────────────────────────────────────────────

@router.delete("/users/{username}/token-factory/{path_slug}")
def api_delete_token(request: Request, username: str, path_slug: str):
    user, token = _resolve_token(request, username, path_slug)
    try:
        svc_tokens.delete_token(user.id, token.id)
    except svc_tokens.TokenNotFound as e:
        raise HTTPException(404, str(e)) from e
    except svc_tokens.TokenAuthError as e:
        raise HTTPException(403, str(e)) from e
    return JSONResponse({"ok": True})


# ── relink board ──────────────────────────────────────────────────────────────

@router.post("/users/{username}/token-factory/{path_slug}/api/relink-board")
def api_relink_board(
    request: Request, username: str, path_slug: str, body: RelinkBoardBody
):
    user, token = _resolve_token(request, username, path_slug)
    try:
        summary = svc_tokens.relink_board(
            user.id, token.id, body.linked_board_id
        )
    except svc_tokens.DesignGateError as e:
        raise HTTPException(409, str(e)) from e
    except (svc_tokens.BoardAuthError, svc_tokens.TokenAuthError) as e:
        raise HTTPException(403, str(e)) from e
    return JSONResponse({"token": svc_tokens._summary_to_dict(summary)})


# ── design explore ────────────────────────────────────────────────────────────

@router.post("/users/{username}/token-factory/{path_slug}/api/explore")
async def api_design_explore(
    request: Request, username: str, path_slug: str
):
    user, token = _resolve_token(request, username, path_slug)

    keys = deps.user_provider_api_keys(request)
    fn = _pipeline_callable_for_token(
        token,
        functools.partial(
            _import_design_explore_job(),
            token_id=token.id,
            openai_key=keys.get("openai_key"),
        ),
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Explore {token.slug}",
        operation="token.design_explore",
        target=token.slug,
        cost_estimate=svc_tokens.estimate_explore_cost_usd(),
        fn=fn,
    )
    return JSONResponse({"job_id": job_id})


# ── commit canonical ──────────────────────────────────────────────────────────

@router.post(
    "/users/{username}/token-factory/{path_slug}/api/commit-canonical"
)
def api_commit_canonical(
    request: Request, username: str, path_slug: str, body: CommitCanonicalBody
):
    user, token = _resolve_token(request, username, path_slug)
    if token.linked_board_id:
        board_palette = svc_tokens.board_palette_rgb_tuples(token.linked_board_id)
    else:
        board_palette = []  # palette.compute_token_palette returns neutral fallback

    try:
        summary = svc_tokens.commit_canonical(
            user_id=user.id,
            token_id=token.id,
            candidate_index=body.candidate_index,
            style_sentence=body.style_sentence,
            board_palette_colors=board_palette,
        )
    except svc_tokens.DesignGateError as e:
        raise HTTPException(400, str(e)) from e
    except svc_tokens.TokenAuthError as e:
        raise HTTPException(403, str(e)) from e
    return JSONResponse({"token": svc_tokens._summary_to_dict(summary)})


# ── unlock design ─────────────────────────────────────────────────────────────

@router.post("/users/{username}/token-factory/{path_slug}/api/unlock")
def api_unlock_design(request: Request, username: str, path_slug: str):
    user, token = _resolve_token(request, username, path_slug)
    try:
        summary = svc_tokens.unlock_design(user.id, token.id)
    except svc_tokens.TokenAuthError as e:
        raise HTTPException(403, str(e)) from e
    return JSONResponse({"token": svc_tokens._summary_to_dict(summary)})


# ── generate clip ─────────────────────────────────────────────────────────────

@router.post("/users/{username}/token-factory/{path_slug}/api/clips/{clip_name}")
async def api_generate_clip(
    request: Request, username: str, path_slug: str, clip_name: str
):
    user, token = _resolve_token(request, username, path_slug)
    try:
        svc_tokens.assert_design_locked(token)
    except svc_tokens.DesignGateError as e:
        raise HTTPException(400, str(e)) from e

    keys = deps.user_provider_api_keys(request)
    fn = _pipeline_callable_for_token(
        token,
        functools.partial(
            _import_generate_clip_job(),
            token_id=token.id,
            clip_name=clip_name,
            openai_key=keys.get("openai_key"),
        ),
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Clip {token.slug}/{clip_name}",
        operation="token.generate_clip",
        target=f"{token.slug}/{clip_name}",
        cost_estimate=svc_tokens.estimate_clip_cost_usd(),
        fn=fn,
    )
    return JSONResponse({"job_id": job_id})


# ── pack + publish ─────────────────────────────────────────────────────────────

@router.post("/users/{username}/token-factory/{path_slug}/api/publish")
async def api_pack_publish(request: Request, username: str, path_slug: str):
    user, token = _resolve_token(request, username, path_slug)
    try:
        svc_tokens.assert_design_locked(token)
    except svc_tokens.DesignGateError as e:
        raise HTTPException(400, str(e)) from e

    fn = _pipeline_callable_for_token(
        token,
        functools.partial(_import_pack_publish_job(), token_id=token.id),
    )
    job_id = deps.enqueue_pipeline_job(
        label=f"Publish {token.slug}",
        operation="token.pack_publish",
        target=token.slug,
        cost_estimate=0.0,
        fn=fn,
    )
    return JSONResponse({"job_id": job_id})


# ── payload ────────────────────────────────────────────────────────────────────

@router.get("/users/{username}/token-factory/{path_slug}/api/payload")
def api_token_payload(request: Request, username: str, path_slug: str):
    user, token = _resolve_token(request, username, path_slug)
    return JSONResponse(
        svc_tokens.build_token_detail_payload(
            token.id, token_asset_base=_token_asset_base(username, path_slug)
        )
    )


# ── job status ─────────────────────────────────────────────────────────────────

@router.get("/users/{username}/token-factory/{path_slug}/api/job/{job_id}")
def api_token_job_status(
    request: Request, username: str, path_slug: str, job_id: str
):
    user, token = _resolve_token(request, username, path_slug)
    from jobs.runner import get_runner

    runner = get_runner()
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JSONResponse(
        {
            "job_id": job_id,
            "status": job.status,
            "events": job.events,
        }
    )


# ── asset route ────────────────────────────────────────────────────────────────

@router.get("/users/{username}/token-factory/{path_slug}/asset/{rest:path}")
def token_asset(request: Request, username: str, path_slug: str, rest: str):
    user, token = _resolve_token(request, username, path_slug)
    try:
        target = token_ws.safe_token_relative(token.id, rest)
    except token_ws.PathTraversalError:
        raise HTTPException(400, "Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})


# ── deferred imports — keep web boot cheap ────────────────────────────────────

def _import_design_explore_job():
    from domains.tokens.pipeline_jobs import design_explore_job
    return design_explore_job


def _import_generate_clip_job():
    from domains.tokens.pipeline_jobs import generate_clip_job
    return generate_clip_job


def _import_pack_publish_job():
    from domains.tokens.pipeline_jobs import pack_publish_job
    return pack_publish_job

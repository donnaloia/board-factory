"""Space animation pipeline job workers (``domains.spaces.animations``).

Pipeline imports happen INSIDE each worker so importing this module from
web boot stays cheap.

The worker:

  1. Resolves the source live PNG bytes for the cell.
  2. Builds an ``AnimateSpec`` and runs ``space_animations.ops.animate_space``.
  3. Forwards progress through a ``JobProgressSink`` so the SSE channel
     reflects per-candidate progress.
  4. Records realized cost in the ledger when the provider charges for it
     (the OpenAI provider does; the mock provider is free).

Promotion happens later, on the explicit ``commit`` HTTP call. The worker
never touches DB rows for ``space_animations`` — that's the service layer's
job after the user picks a candidate.
"""

from __future__ import annotations

import threading

from sqlalchemy import select

from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from jobs import cost_ledger
from jobs.runner import Job, JobProgressSink, check_cancel, get_runner
from domains.spaces.assets.models import AssetVersionRecord
from domains.spaces.models import CellRecord


def animate_space_job(
    job: Job,
    cancel: threading.Event,
    *,
    board_id: str,
    cell_id: str,
    openai_key: str | None = None,
    animation_prompt: str = "",
) -> float:
    """Produce 3 candidate loops for ``cell_id`` on ``board_id``.

    ``openai_key`` is the per-user API key, threaded in from the route
    via ``functools.partial``. The default provider (``openai``) needs
    it; the ``mock`` provider ignores it.
    """
    from pathlib import Path

    from space_animations import config as anim_config
    from space_animations.ops import AnimateSpec, animate_space
    from space_animations.providers.factory import select_provider

    from domains.spaces.animations import manifest_io

    check_cancel(cancel)
    cell, source_png, source_av_id, source_basename = _load_source(board_id, cell_id)
    check_cancel(cancel)

    proposal_dir: Path = manifest_io.proposal_dir(board_id, cell_id, job.id)

    spec = AnimateSpec(
        job_id=job.id,
        cell_id=cell_id,
        source_png=source_png,
        source_asset_version_id=source_av_id,
        source_basename=source_basename,
        proposal_dir=proposal_dir,
        fps=anim_config.target_fps(),
        duration_ms=anim_config.target_duration_ms(),
        candidates=anim_config.candidates(),
        encoding=anim_config.default_encoding(),
        loop_strategy=anim_config.default_loop_strategy(),
        animation_prompt=animation_prompt,
    )
    provider = select_provider(
        anim_config.provider_name(),
        openai_api_key=openai_key,
    )

    sink = JobProgressSink(job, runner=get_runner())
    prompt_preview = (animation_prompt or "").strip().replace("\n", " ")
    if len(prompt_preview) > 160:
        prompt_preview = prompt_preview[:157] + "…"
    if prompt_preview:
        sink.log(f"animation prompt: {prompt_preview}")
    result = animate_space(spec, provider, sink)
    check_cancel(cancel)

    if result.spent_usd > 0:
        cost_ledger.record(
            "animate.space", cell.slug, len(result.candidates), result.spent_usd
        )

    job.log.append(
        f"animated cell:{cell.slug} ({len(result.candidates)} candidates) "
        f"with {provider.name}/{provider.model_id}"
    )
    return float(result.spent_usd)


def _load_source(board_id: str, cell_id: str) -> tuple[CellRecord, bytes, int | None, str | None]:
    """Read the cell's live static PNG bytes + the source asset_version row id.

    Fails fast (per .cursorrules) if either the cell or its live static art is
    missing — the gate in the routes layer should have caught this, but we
    defend in depth so a misconfigured worker does not produce 0-byte clips.
    """
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        if cell is None or cell.board_uuid != board_id:
            raise RuntimeError(
                f"Cell {cell_id!r} not found on board {board_id!r}; "
                "animate job cannot proceed."
            )
        if cell.live_asset_version_id is None:
            raise RuntimeError(
                f"Cell {cell_id!r} has no live_asset_version_id; "
                "live static art is required before animation (spec §G1)."
            )
        av = session.scalar(
            select(AssetVersionRecord).where(
                AssetVersionRecord.id == cell.live_asset_version_id
            )
        )
        if av is None:
            raise RuntimeError(
                f"asset_versions row {cell.live_asset_version_id} referenced by "
                f"cell {cell_id!r} is missing."
            )
        slug = cell.slug
        kind = cell.kind
        av_id = av.id
        av_basename = av.basename
        session.expunge(cell)

    live_path = _resolve_live_static_path(board_id, kind, slug)
    if not live_path.exists():
        raise RuntimeError(
            f"Live static PNG missing on disk at {live_path}; "
            "promotion may have failed silently."
        )
    return cell, live_path.read_bytes(), av_id, av_basename


def _resolve_live_static_path(board_id: str, kind: str, slug: str):
    """Map ``cells.kind`` to the legacy filesystem ``category`` for live PNGs."""
    if kind == "perimeter":
        category = "spaces"
    elif kind == "functional":
        category = "panels"
    elif kind == "centerpiece":
        category = "centerpiece"
    else:
        raise RuntimeError(f"Unknown cell kind {kind!r}")
    return fs_ws.live_path(board_id, category, slug)

"""Token Factory pipeline job workers (``domains.tokens``).

Same shape as other ``domains/*/pipeline_jobs.py`` modules:

    fn(job: Job, cancel: threading.Event, **kwargs) -> float | None

Pipeline imports deferred inside each worker so web boot stays cheap.

After the Token Factory decoupling, every workspace path is keyed by
``token_id`` (not by board); the optional ``linked_board_id`` is only used
for ``pack_publish``'s manifest metadata.
"""

from __future__ import annotations

import threading

from jobs import cost_ledger
from jobs.runner import Job, JobProgressSink, get_runner


# ── cost estimates exposed to the UI without importing the pipeline ──
DESIGN_EXPLORE_COST_USD: float = 0.12
GENERATE_CLIP_COST_USD: float = 0.20
PACK_PUBLISH_COST_USD: float = 0.00


# ────────────────────────── design explore ──────────────────────────


def design_explore_job(
    job: Job,
    cancel: threading.Event,
    *,
    token_id: str,
    openai_key: str,
) -> float | None:
    """Generate reference candidates for a token."""
    from tokenfactory.config import CANDIDATE_COUNT, provider_name
    from tokenfactory.ops.design_explore import design_explore
    from tokenfactory.providers.factory import select_provider
    from domains.tokens import repository as tokens_repo
    from domains.tokens import services as tokens_svc
    from domains.tokens import workspace as token_ws

    row = tokens_repo.get_token(token_id)
    if row is None:
        raise LookupError(f"Token {token_id!r} not found")

    style_sentence, token_palette = tokens_svc.resolve_design_explore_inputs(row)

    sink = JobProgressSink(job, get_runner())
    prov = select_provider(provider_name(), openai_key=openai_key)

    paths = design_explore(
        candidates_dir=token_ws.candidates_dir(row.id),
        canvas_w=row.canvas_w,
        canvas_h=row.canvas_h,
        style_sentence=style_sentence,
        token_palette=token_palette,
        locomotion_profile=row.locomotion_profile,
        sink=sink,
        provider=prov,
        count=CANDIDATE_COUNT,
    )

    cost = prov.cost_estimate_usd(n_candidates=len(paths), n_frames=0)
    cost_ledger.record("token.design_explore", row.slug, len(paths), cost)
    return cost


# ────────────────────────── generate clip ──────────────────────────


def generate_clip_job(
    job: Job,
    cancel: threading.Event,
    *,
    token_id: str,
    clip_name: str,
    openai_key: str,
) -> float | None:
    """Generate all frames for one animation clip."""
    from tokenfactory.config import CLIPS_BY_LOCOMOTION, provider_name
    from tokenfactory.ops.generate_clip import generate_clip
    from tokenfactory.providers.factory import select_provider
    from domains.tokens import repository as tokens_repo
    from domains.tokens import workspace as token_ws
    from domains.tokens.services import assert_design_locked

    from PIL import Image

    row = tokens_repo.get_token(token_id)
    if row is None:
        raise LookupError(f"Token {token_id!r} not found")

    assert_design_locked(row)

    lock = token_ws.read_design_lock(row.id)
    if lock is None:
        raise RuntimeError(f"design_lock.json missing for token {row.slug!r}")

    clip_defs = CLIPS_BY_LOCOMOTION.get(row.locomotion_profile, [])
    clip_def = next(
        ((n, fc, ki) for n, fc, ki in clip_defs if n == clip_name), None
    )
    if clip_def is None:
        raise ValueError(
            f"Clip {clip_name!r} is not defined for locomotion "
            f"profile {row.locomotion_profile!r}."
        )
    _, frame_count, key_frame_indices = clip_def

    canonical_path = token_ws.canonical_png_path(row.id)
    if not canonical_path.exists():
        raise RuntimeError(
            f"canonical.png missing for token {row.slug!r}. "
            "Commit a design candidate first."
        )
    canonical_img = Image.open(str(canonical_path)).convert("RGBA")

    sink = JobProgressSink(job, get_runner())
    prov = select_provider(provider_name(), openai_key=openai_key)

    generate_clip(
        clip_name=clip_name,
        canonical_img=canonical_img,
        keys_dir=token_ws.clip_keys_dir(row.id, clip_name),
        frames_dir=token_ws.clip_frames_dir(row.id, clip_name),
        frame_count=frame_count,
        key_frame_indices=key_frame_indices,
        canvas_w=row.canvas_w,
        canvas_h=row.canvas_h,
        style_sentence=lock.get("style_sentence", ""),
        token_palette=lock.get("token_palette", {}),
        locomotion_profile=row.locomotion_profile,
        provider=prov,
        sink=sink,
    )

    cost = prov.cost_estimate_usd(n_candidates=0, n_frames=frame_count)
    cost_ledger.record(
        "token.generate_clip", f"{row.slug}/{clip_name}", frame_count, cost
    )
    return cost


# ────────────────────────── pack + publish ──────────────────────────


def pack_publish_job(
    job: Job,
    cancel: threading.Event,
    *,
    token_id: str,
) -> float | None:
    """Pack all clips into atlas and publish to live/."""
    from tokenfactory.ops.pack_publish import pack_publish
    from tokenfactory.schemas.manifest import DesignLock
    from domains.tokens import repository as tokens_repo
    from domains.tokens import workspace as token_ws
    from domains.tokens.services import assert_design_locked

    row = tokens_repo.get_token(token_id)
    if row is None:
        raise LookupError(f"Token {token_id!r} not found")

    assert_design_locked(row)

    lock_raw = token_ws.read_design_lock(row.id)
    if lock_raw is None:
        raise RuntimeError(f"design_lock.json missing for token {row.slug!r}")

    lock = DesignLock(**lock_raw)
    run_id = token_ws.new_run_id()

    sink = JobProgressSink(job, get_runner())

    clips_root = token_ws.token_root(row.id) / "clips"
    live_dir = token_ws.animations_live_dir(row.id)
    history_dir = token_ws.animations_history_dir(row.id, run_id)

    pack_publish(
        token_slug=row.slug,
        board_id=row.linked_board_id or "",
        design_lock=lock,
        clips_root=clips_root,
        live_dir=live_dir,
        history_dir=history_dir,
        run_id=run_id,
        sink=sink,
    )

    tokens_repo.set_live_run_id(token_id, run_id)
    if PACK_PUBLISH_COST_USD > 0:
        cost_ledger.record("token.pack_publish", run_id, 1, PACK_PUBLISH_COST_USD)
    return PACK_PUBLISH_COST_USD

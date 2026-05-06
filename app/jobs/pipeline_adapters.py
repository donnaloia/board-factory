"""Plain pipeline-job functions bound to the in-process JobRunner.

Each function here is a worker callable with the standard signature

    fn(job: Job, cancel: threading.Event) -> float | None

returning the realized cost in USD (the runner uses it to fill in
``job.cost_actual``). Inside, each function:

  1. validates inputs (catalog exists, mockup OK, etc.) and raises early
  2. constructs a ``JobProgressSink`` so the pipeline op can stream
     per-step progress into ``job.progress`` + ``job.log``
  3. runs the underlying op
  4. records cost into the ledger when the op talked to a paid provider

Parameterized variants (analyze needs an OpenAI key, generate_one needs
a category + asset id, etc.) take their parameters as keyword args. Route
handlers wrap them with ``functools.partial`` to fix the parameters before
handing the function to ``deps.enqueue_pipeline_job``.

The web layer never imports ``boardfactory`` directly — pipeline imports
stay inside the worker functions so web boot stays cheap.
"""

from __future__ import annotations

import threading

from jobs import cost_ledger
from jobs.runner import Job, JobProgressSink, check_cancel, get_runner

# Exposed so the web UI can show an estimate on the action tile without
# importing the full pipeline package at import time.
ANALYZE_COST_USD: float = 0.08


# ────────────────────────── catalog & provider helpers ──────────────────────────


def _load_catalog():
    from boardfactory import config

    from domains.boards import services as bd

    bid = config.active_board()
    if not bid:
        raise RuntimeError("No active board set for pipeline job")
    cat = bd.load_catalog_model(bid)
    if cat is None:
        raise RuntimeError(
            f"No catalog in database for board {bid!r}. "
            "Import or create the board spec before running pipeline jobs."
        )
    return cat


def _validate_mockup_or_die(catalog) -> None:
    from boardfactory import config
    from boardfactory.geometry import (
        MockupAspectMismatch,
        validate_mockup_dimensions,
    )

    mockup_path = config.BOARD_ROOT / catalog.style.reference_image
    try:
        validate_mockup_dimensions(mockup_path, canvas_size=catalog.board_size, strict=True)
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from None
    except MockupAspectMismatch as e:
        raise RuntimeError(f"Mockup aspect ratio incompatible with catalog: {e}") from None


def _sink(job: Job) -> JobProgressSink:
    """A sink that publishes through the active job runner so SSE updates fire."""
    return JobProgressSink(job, runner=get_runner())


def _resolve_provider(
    pixellab_key: str | None = None,
    openai_key: str | None = None,
    *,
    catalog=None,
):
    """Return the configured provider with per-user keys + board settings.

    Keys are passed through to the provider constructor instead of being
    written into ``os.environ`` (which used to introduce request-scoped
    side effects on a process-global namespace). The provider falls back
    to its env var if neither this caller nor the route handler injected
    a key, so the legacy ``OPENAI_API_KEY`` / ``PIXELLAB_API_KEY`` flow
    still works.

    When ``catalog`` is provided, its ``generation`` block selects the
    provider, model, and quality/preset — overriding the env-level
    ``BOARDFACTORY_PROVIDER`` value.
    """
    from boardfactory.providers import get_provider

    settings = getattr(catalog, "generation", None) if catalog is not None else None
    return get_provider(
        settings=settings,
        pixellab_api_key=pixellab_key,
        openai_api_key=openai_key,
    )


# ────────────────────────── cost estimators ──────────────────────────


def estimate_style() -> float:
    return 0.0  # local-only, no provider call


def estimate_generate(category: str) -> float:
    """Roughly estimate cost in USD for a full category generation.

    Used for the global header estimates (purely informational). The actual
    spend per category is dominated by the unique-design count, not by the
    number of board positions.
    """
    from boardfactory import config

    if category == "spaces":
        return float(config.space_candidates()) * 0.015 * 8       # designs vary, ~8 designs
    if category == "panels":
        return float(config.panel_candidates()) * 0.015 * 12      # ~12 panels
    if category == "centerpiece":
        return float(config.centerpiece_candidates()) * 0.022     # higher per call
    return 0.0


def estimate_generate_one(category: str, target: str | None = None) -> float:
    """Cost of regenerating one cell (one design / panel / centerpiece)."""
    from boardfactory import config

    if category == "centerpiece":
        return float(config.centerpiece_candidates()) * 0.022
    if category == "panels":
        return float(config.panel_candidates()) * 0.015
    if category == "spaces":
        return float(config.space_candidates()) * 0.015
    return 0.0


# Backwards-compat alias — both names point at the same implementation.
estimate_regen_one = estimate_generate_one


def estimate_generate_all(
    missing_space_count: int,
    missing_panel_count: int,
) -> float:
    """Combined cost estimate for generate-all (spaces + panels)."""
    return (
        estimate_generate_one("spaces") * missing_space_count
        + estimate_generate_one("panels") * missing_panel_count
    )


# ────────────────────────── per-cell + style + cleanup ──────────────────────────


def analyze(job: Job, cancel: threading.Event, *, openai_key: str) -> float:
    """Send the board mockup to GPT-4o vision and write back per-cell prompts.

    The openai_key is passed in by the route handler (resolved from the
    requesting user's profile so different artists can use their own keys).
    """
    from pathlib import Path

    from boardfactory import config
    from boardfactory.ops import ANALYZE_COST_USD as _ACOST, analyze_mockup

    catalog = _load_catalog()
    check_cancel(cancel)

    mockup_path = Path(config.BOARD_ROOT) / catalog.style.reference_image
    if not mockup_path.exists():
        raise RuntimeError(
            f"Mockup not found at {mockup_path}. "
            "Upload a reference image before running analysis."
        )

    result = analyze_mockup(catalog, mockup_path, openai_key, _sink(job))
    check_cancel(cancel)

    bid = config.active_board()
    if not bid:
        raise RuntimeError("No active board")
    import domains.boards.services as svc_catalog  # noqa: PLC0415

    data = svc_catalog.load_catalog(bid)

    if result["style_prompt"]:
        data.setdefault("style", {})["prompt"] = result["style_prompt"]

    designs_by_id = {d["id"]: d for d in data.get("board_spaces", {}).get("designs", [])}
    for did, prompt in result["designs"].items():
        if prompt and did in designs_by_id:
            designs_by_id[did]["prompt"] = prompt

    panels_by_id = {
        p["id"]: p
        for p in data.get("feature_panels", {}).get("panels", [])
    }
    for pid, prompt in result["panels"].items():
        if prompt and pid in panels_by_id:
            panels_by_id[pid]["prompt"] = prompt

    if result["centerpiece"]:
        data.setdefault("centerpiece", {})["prompt"] = result["centerpiece"]

    svc_catalog.save_catalog(bid, data)

    n_written = (
        sum(1 for v in result["designs"].values() if v)
        + sum(1 for v in result["panels"].values() if v)
        + bool(result["centerpiece"])
        + bool(result["style_prompt"])
    )
    job.log.append(
        f"wrote {n_written} prompts to catalog  "
        f"(spent ~${_ACOST:.2f} estimated)"
    )
    return _ACOST


def style(job: Job, cancel: threading.Event) -> float:
    """Style Lock step: extract palette + style sheet from the mockup."""
    from boardfactory.steps.style_lock import do_style_lock

    catalog = _load_catalog()
    _validate_mockup_or_die(catalog)
    check_cancel(cancel)

    do_style_lock(catalog, _sink(job))
    check_cancel(cancel)
    try:
        from boardfactory import config as _cfg

        bid = _cfg.active_board()
        if bid:
            from domains.boards import palette as _wp

            _wp.persist_palette_from_style_dir(bid)
    except Exception:
        pass
    return 0.0


def generate_one(
    job: Job,
    cancel: threading.Event,
    *,
    category: str,
    asset_id: str,
    prompt_override: str | None = None,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> float:
    """Regenerate exactly one cell (auto-promotes to live).

    prompt_override: if provided, used in place of the catalog prompt for
    this generation. Stored on the new history entries' sidecar so the
    side panel can show 'this is the prompt that made this art'.
    """
    from boardfactory.ops import (
        draw_cell,
        spec_for_centerpiece,
        spec_for_panel,
        spec_for_space,
    )

    catalog = _load_catalog()
    from boardfactory import assets as bf_assets

    if category in ("spaces", "panels"):
        _validate_mockup_or_die(catalog)
    elif category == "centerpiece":
        # Initial centerpiece is img2img from mockup; regeneration is txt2img.
        if not bf_assets.has_live("centerpiece", "centerpiece"):
            _validate_mockup_or_die(catalog)
    provider = _resolve_provider(pixellab_key, openai_key, catalog=catalog)
    check_cancel(cancel)

    if category == "spaces":
        spec = spec_for_space(catalog, asset_id, prompt_override=prompt_override)
    elif category == "panels":
        spec = spec_for_panel(catalog, asset_id, prompt_override=prompt_override)
    elif category == "centerpiece":
        spec = spec_for_centerpiece(catalog, prompt_override=prompt_override)
    else:
        raise RuntimeError(f"Unknown category: {category!r}")

    result = draw_cell(spec, provider, _sink(job))
    check_cancel(cancel)
    cost_ledger.record(f"regen.{category}", asset_id, 1, result.spent_usd)
    job.log.append(
        f"promoted: {result.promoted_filename or '(none)'}  "
        f"history+={len(result.history_filenames)}"
    )
    return result.spent_usd


def generate_missing(
    job: Job,
    cancel: threading.Event,
    *,
    category: str,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> float:
    """Generate every cell of this category that has no live asset.

    One umbrella job with internal N-of-M progress. Categories:
      - "spaces"      → generate every space design that's missing a live asset
      - "panels"      → generate every functional panel that's missing one
      - "centerpiece" → only one cell, but kept here for adapter symmetry
    """
    from boardfactory.ops import (
        generate_centerpiece,
        generate_missing_panels,
        generate_missing_spaces,
    )

    catalog = _load_catalog()
    _validate_mockup_or_die(catalog)
    provider = _resolve_provider(pixellab_key, openai_key, catalog=catalog)
    check_cancel(cancel)

    sink = _sink(job)
    if category == "spaces":
        results = generate_missing_spaces(catalog, provider, sink)
    elif category == "panels":
        results = generate_missing_panels(catalog, provider, sink)
    elif category == "centerpiece":
        results = [generate_centerpiece(catalog, provider, sink)]
    else:
        raise RuntimeError(f"Unknown category: {category!r}")

    check_cancel(cancel)
    spent = sum(r.spent_usd for r in results)
    cost_ledger.record(f"generate.{category}", None, len(results), spent)
    job.log.append(
        f"generated {sum(1 for r in results if r.promoted_filename)} / "
        f"{len(results)} {category}  (spent ${spent:.2f})"
    )
    return spent


def generate_all(
    job: Job,
    cancel: threading.Event,
    *,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> float:
    """Generate every empty space AND every empty UI panel.

    Runs spaces first then panels, each as a sub-pass, so the job progress
    reflects the combined total of missing assets.
    """
    from boardfactory.ops import generate_missing_panels, generate_missing_spaces

    catalog = _load_catalog()
    _validate_mockup_or_die(catalog)
    provider = _resolve_provider(pixellab_key, openai_key, catalog=catalog)
    check_cancel(cancel)

    sink = _sink(job)
    space_results = generate_missing_spaces(catalog, provider, sink)
    check_cancel(cancel)
    panel_results = generate_missing_panels(catalog, provider, sink)
    check_cancel(cancel)

    all_results = space_results + panel_results
    spent = sum(r.spent_usd for r in all_results)
    cost_ledger.record("generate.all", None, len(all_results), spent)
    job.log.append(
        f"generated {sum(1 for r in all_results if r.promoted_filename)} / "
        f"{len(all_results)} assets  (spent ${spent:.2f})"
    )
    return spent


def clean_one(
    job: Job,
    cancel: threading.Event,
    *,
    category: str,
    asset_id: str,
) -> float:
    """Re-clean the live image of one cell. Free, fast.

    Re-runs palette quantize + grid-snap on the current live PNG, pushes
    the result to history with operation=clean, and promotes it as the
    new live. Useful when the palette changed after generation.
    """
    from boardfactory import assets as bf_assets

    check_cancel(cancel)
    sink = _sink(job)
    sink.start(f"clean {category}/{asset_id}", total=1)
    try:
        new_name = bf_assets.reclean_live(category, asset_id)
    except RuntimeError as e:
        sink.log(f"FAIL: {e}")
        raise
    sink.step(new_name or "(no change)")
    sink.log(f"promoted cleaned -> live/{category}/{asset_id}")
    return 0.0


# ────────────────────────── board-level (states / preview / export) ──────────────────────────


def states(job: Job, cancel: threading.Event) -> float:
    """Active-States step."""
    from boardfactory.steps.states import do_states

    catalog = _load_catalog()
    do_states(catalog, _sink(job))
    check_cancel(cancel)
    return 0.0


def preview(job: Job, cancel: threading.Event) -> float:
    """Composite Preview step."""
    from boardfactory.steps.compositor import do_preview

    catalog = _load_catalog()
    _validate_mockup_or_die(catalog)
    do_preview(catalog, _sink(job))
    check_cancel(cancel)
    return 0.0


def export(job: Job, cancel: threading.Event) -> float:
    """Export step."""
    from boardfactory.steps.export import do_export

    catalog = _load_catalog()
    do_export(catalog, _sink(job))
    check_cancel(cancel)
    return 0.0


# ────────────────────────── frame customization ──────────────────────────


# Canonical proposal layout under each board's workspace:
#
#   workspace/frames/_proposals/<job_id>/
#     manifest.json     — list of candidates with bbox/ring/score/notes
#     candidate_<i>.png       — overlay-on-source preview for the Atelier UI
#     candidate_<i>_hole.png  — L-mode hole mask
#     candidate_<i>_rim.png   — L-mode rim mask
#
# Routes serve these directly via the existing static-asset path.


def frame_propose(
    job: Job,
    cancel: threading.Event,
    *,
    source_kind: str,
    source_id: str,
    candidate_count: int = 3,
    openai_key: str | None = None,
    use_vision: bool = True,
) -> float:
    """Atelier "Propose" step — vision (or deterministic) frame candidates.

    Writes a manifest + preview overlays so the UI can poll
    ``GET /api/frame/proposals/<job_id>`` for the candidate list as soon
    as the job goes terminal. Falls back to ``MockFrameVision`` when
    ``use_vision`` is false or no key is available, so users without an
    OpenAI key still get the Atelier flow with the deterministic 9-slice
    candidates today's pipeline already supports.
    """
    import json as _json

    from boardfactory import config as bf_config
    from boardfactory import frames_inference as fi
    from boardfactory.providers.vision import (
        MockFrameVision,
        OpenAIFrameVision,
    )

    sink = _sink(job)
    sink.start("propose frame", total=4)

    catalog = _load_catalog()
    bid = bf_config.active_board()
    if not bid:
        raise RuntimeError("No active board for frame_propose")

    src_img, src_size, panel_size = _load_frame_source(catalog, source_kind, source_id)
    sink.step(f"source loaded ({src_size[0]}×{src_size[1]})")
    check_cancel(cancel)

    # Pick the provider. Vision off -> deterministic candidates; vision on
    # but no key -> log + fall back so the UI still works without a key.
    provider = None
    if use_vision and openai_key:
        try:
            provider = OpenAIFrameVision(api_key=openai_key)
        except RuntimeError as e:
            sink.log(f"vision disabled: {e}")
            provider = None
    if provider is None:
        provider = MockFrameVision()
        sink.log(f"using {provider.name} provider for proposals")

    raw_candidates = provider.segment_frame(
        src_img, candidate_count=candidate_count
    )
    sink.step(f"vision returned {len(raw_candidates)} candidate(s)")
    check_cancel(cancel)

    cleaned: list[fi.CandidateGeometry] = []
    if not raw_candidates:
        # Always offer at least the deterministic shortcut so the user can
        # commit something today. Ring sized to ~1/16 of the smaller side.
        smallest = min(src_size)
        ring = max(2, smallest // 16)
        cleaned.append(
            fi.candidate_from_ring(
                source_size=src_size, ring_px=ring, score=0.6,
                notes="deterministic fallback (vision returned 0 candidates)",
            )
        )
    else:
        for c in raw_candidates:
            try:
                cleaned.append(
                    fi.candidate_from_outer_inner(
                        source_size=src_size,
                        outer=c.outer_mask,
                        inner=c.inner_mask,
                        score=c.score,
                        notes=c.notes,
                    )
                )
            except Exception as e:  # noqa: BLE001 — drop bad candidates, keep going.
                sink.log(f"discarded candidate: {e}")

    if not cleaned:
        raise RuntimeError("no usable frame candidates produced")
    sink.step(f"cleaned {len(cleaned)} candidate(s)")
    check_cancel(cancel)

    # Persist proposals on disk as JSON + preview PNGs so the Atelier can
    # pick them up via a regular HTTP fetch (no SSE polling for payload).
    out_dir = bf_config.WORKSPACE / "frames" / "_proposals" / job.id
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for i, cand in enumerate(cleaned):
        overlay = fi.overlay_for_review(src_img, cand.rim_mask, cand.hole_mask)
        overlay_p = out_dir / f"candidate_{i}.png"
        overlay.save(overlay_p)

        hole_p = out_dir / f"candidate_{i}_hole.png"
        rim_p = out_dir / f"candidate_{i}_rim.png"
        cand.hole_mask.save(hole_p)
        cand.rim_mask.save(rim_p)

        manifest.append({
            "index": i,
            "bbox": list(cand.bbox),
            "ring_px": cand.ring_px,
            "score": cand.score,
            "notes": cand.notes,
            "model_id": getattr(provider, "model_id", provider.name),
            "preview_filename": overlay_p.name,
            "hole_mask_filename": hole_p.name,
            "rim_mask_filename": rim_p.name,
        })

    (out_dir / "manifest.json").write_text(_json.dumps({
        "job_id": job.id,
        "source_kind": source_kind,
        "source_id": source_id,
        "source_size": list(src_size),
        "panel_size": list(panel_size),
        "provider": provider.name,
        "model_id": getattr(provider, "model_id", provider.name),
        "candidates": manifest,
    }, indent=2))

    sink.step(f"wrote {len(manifest)} proposal(s) to {out_dir.name}")

    realized_cost = provider.cost_estimate(len(cleaned))
    if realized_cost > 0:
        cost_ledger.record("frame.propose", source_id, len(cleaned), realized_cost)
    job.log.append(
        f"proposed {len(manifest)} frame candidate(s) "
        f"({source_kind}:{source_id}) via {provider.name}"
    )

    return float(realized_cost)


def frame_reapply(
    job: Job,
    cancel: threading.Event,
    *,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> float:
    """Atelier "Commit" follow-up — Approach D batch regen for panels.

    Iterates every panel the catalog enables for frames; per panel,
    snapshots the previous live into history (tagged ``frame_rework_pre``)
    and inpaints a new interior under the freshly-adopted rim. Cancels
    cleanly between panels so the user can stop the batch without losing
    the panels already done.

    Cost: estimated upfront on enqueue (see ``estimate_reapply_cost``);
    actual cost is the sum of per-panel costs.
    """
    from boardfactory.ops import applicable_panels, reapply_to_panel

    catalog = _load_catalog()
    sink = _sink(job)

    panel_ids = applicable_panels(catalog)
    if not panel_ids:
        sink.log("no panels in scope for Approach D — nothing to do")
        sink.start("reapply frame to panels", total=1)
        sink.step("no-op")
        return 0.0

    provider = _resolve_provider(pixellab_key, openai_key, catalog=catalog)
    sink.start("reapply frame to panels", total=len(panel_ids))
    sink.log(
        f"approach D: rewriting {len(panel_ids)} panel interior(s) "
        f"under the new house frame (provider={provider.name})"
    )

    spent = 0.0
    successes = 0
    failures: list[str] = []
    for pid in panel_ids:
        check_cancel(cancel)
        result = reapply_to_panel(catalog, pid, provider, sink)
        spent += float(result.spent_usd)
        if result.skipped:
            sink.log(f"panel:{pid} skipped (no live yet)")
            continue
        if result.error:
            failures.append(f"panel:{pid}: {result.error}")
            sink.log(f"panel:{pid} FAILED: {result.error}")
            continue
        if result.promoted_filename:
            successes += 1

    if spent > 0:
        cost_ledger.record("frame.reapply", None, successes, spent)

    summary = f"reapplied frame to {successes} / {len(panel_ids)} panel(s)"
    if failures:
        summary += f" — {len(failures)} failure(s)"
    job.log.append(f"{summary}  (spent ${spent:.2f})")
    if failures:
        for line in failures[:10]:
            job.log.append(line)

    return spent


def _load_frame_source(
    catalog,
    source_kind: str,
    source_id: str,
) -> "tuple[object, tuple[int, int], tuple[int, int]]":
    """Load a frame source image. Returns (PIL image, source_size, panel_size).

    ``panel_size`` is the typical functional-panel target size, used by
    the Atelier to compute the "render at typical size" preview tile.
    """
    from pathlib import Path

    from PIL import Image

    from boardfactory import config as bf_config

    panel_size: tuple[int, int] = (260, 240)
    panels = list(catalog.all_panels())
    if panels:
        panel_size = panels[0].target_size

    if source_kind == "panel":
        from boardfactory import assets as bf_assets

        live = bf_assets.live_path("panels", source_id)
        if not live.exists():
            raise RuntimeError(f"no live panel asset for {source_id!r}")
        img = Image.open(live).convert("RGBA")
        return img, img.size, panel_size

    if source_kind == "mockup":
        panel = next((p for p in panels if p.id == source_id), None)
        if panel is None:
            raise RuntimeError(f"unknown panel {source_id!r} for mockup source")
        mockup_path = bf_config.BOARD_ROOT / catalog.style.reference_image
        if not mockup_path.exists():
            raise RuntimeError(f"mockup not found at {mockup_path}")
        x1, y1, x2, y2 = panel.bbox
        crop = Image.open(mockup_path).convert("RGBA").crop((x1, y1, x2, y2))
        crop = crop.resize(panel.target_size, Image.NEAREST)
        return crop, crop.size, panel.target_size

    if source_kind == "upload":
        upload_path = (
            Path(bf_config.WORKSPACE)
            / "frames"
            / "_uploads"
            / source_id
        )
        if not upload_path.exists():
            raise RuntimeError(f"upload not found at {upload_path}")
        img = Image.open(upload_path).convert("RGBA")
        return img, img.size, panel_size

    raise RuntimeError(f"unknown source_kind {source_kind!r}")

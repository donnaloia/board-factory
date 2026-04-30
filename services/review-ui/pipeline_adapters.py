"""Adapters that bind pipeline ops to the Job runner.

Each adapter:

  1. Builds a worker function `fn(job, cancel) -> cost_actual`
  2. Inside fn:
       - validates inputs (catalog exists, mockup OK, etc.) and raises early
       - constructs a `JobProgressSink` so the pipeline op can stream
         per-step progress into job.progress + job.log
       - runs the underlying op
       - records cost into the ledger when the op talked to a paid provider
       - returns the realized cost so the runner can update job.cost_actual

The web layer never imports `boardfactory` directly; everything goes through
this file. Keeping pipeline imports inside the worker fn keeps web boot
cheap (no PIL / httpx import on import).
"""

from __future__ import annotations

import threading
from typing import Callable

import cost_ledger
from jobs import Job, JobCancelled, JobProgressSink, check_cancel, get_runner

# Exposed so server.py can show an estimate on the action tile without importing
# the full pipeline package at import time.
ANALYZE_COST_USD: float = 0.08


# ────────────────────────── catalog & provider helpers ──────────────────────────


def _load_catalog():
    from boardfactory import config
    from boardfactory.schemas import Catalog

    if not config.CATALOG_PATH.exists():
        raise RuntimeError(
            f"Catalog not found at {config.CATALOG_PATH}. "
            f"This board has no catalog.yml yet."
        )
    return Catalog.load(config.CATALOG_PATH)


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
        return float(config.SPACE_CANDIDATES) * 0.015 * 8       # designs vary, ~8 designs
    if category == "panels":
        return float(config.PANEL_CANDIDATES) * 0.015 * 12      # ~12 panels
    if category == "centerpiece":
        return float(config.CENTERPIECE_CANDIDATES) * 0.022     # higher per call
    return 0.0


def estimate_generate_one(category: str, target: str | None = None) -> float:
    """Cost of regenerating one cell (one design / panel / centerpiece)."""
    from boardfactory import config

    if category == "centerpiece":
        return float(config.CENTERPIECE_CANDIDATES) * 0.022
    if category == "panels":
        return float(config.PANEL_CANDIDATES) * 0.015
    if category == "spaces":
        return float(config.SPACE_CANDIDATES) * 0.015
    return 0.0


# Backwards-compat alias kept so existing server.py call sites still work
# while the rewrite lands. Both names point at the same implementation.
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


def estimate_refine() -> float:
    return 0.022  # one inpaint call


# ────────────────────────── adapters: per-cell + style + cleanup ──────────────────────────


def analyze_adapter(openai_key: str) -> Callable[[Job, threading.Event], float]:
    """Adapter for the mockup-analysis step.

    Sends the board mockup to GPT-4o vision, receives prompt suggestions for
    every design / panel / centerpiece, and writes them back into catalog.yml.
    The style prompt is also written into catalog.style.prompt.

    The openai_key is passed in by the route handler (resolved from the
    requesting user's profile so different artists can use their own keys).
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        from pathlib import Path

        import yaml

        from boardfactory import config
        from boardfactory.ops import ANALYZE_COST_USD, analyze_mockup

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

        # ── patch catalog.yml on disk ──────────────────────────────────────────
        cat_path = config.CATALOG_PATH
        with cat_path.open() as f:
            data = yaml.safe_load(f) or {}

        # style prompt
        if result["style_prompt"]:
            data.setdefault("style", {})["prompt"] = result["style_prompt"]

        # space design prompts
        designs_by_id = {d["id"]: d for d in data.get("board_spaces", {}).get("designs", [])}
        for did, prompt in result["designs"].items():
            if prompt and did in designs_by_id:
                designs_by_id[did]["prompt"] = prompt

        # panel prompts
        panels_by_id = {
            p["id"]: p
            for p in data.get("feature_panels", {}).get("panels", [])
        }
        for pid, prompt in result["panels"].items():
            if prompt and pid in panels_by_id:
                panels_by_id[pid]["prompt"] = prompt

        # centerpiece prompt
        if result["centerpiece"]:
            data.setdefault("centerpiece", {})["prompt"] = result["centerpiece"]

        cat_path.write_text(yaml.safe_dump(data, sort_keys=False))

        n_written = (
            sum(1 for v in result["designs"].values() if v)
            + sum(1 for v in result["panels"].values() if v)
            + bool(result["centerpiece"])
            + bool(result["style_prompt"])
        )
        job.log.append(
            f"wrote {n_written} prompts to catalog.yml  "
            f"(spent ~${ANALYZE_COST_USD:.2f} estimated)"
        )
        return ANALYZE_COST_USD

    return fn


def _resolve_provider(
    pixellab_key: str | None = None,
    openai_key: str | None = None,
):
    """Return the configured provider, injecting per-user keys as needed.

    Temporarily overrides the relevant API key env var so the provider
    constructor reads the user's saved key instead of the compose-level one.
    Falls back to whatever the env var already holds when no key is supplied.
    """
    import os
    from boardfactory.providers import get_provider

    overrides: dict[str, str] = {}
    if pixellab_key:
        overrides["PIXELLAB_API_KEY"] = pixellab_key
    if openai_key:
        overrides["OPENAI_API_KEY"] = openai_key

    if overrides:
        old = {k: os.environ.get(k, "") for k in overrides}
        for k, v in overrides.items():
            os.environ[k] = v
        try:
            return get_provider()
        finally:
            for k, v in old.items():
                os.environ[k] = v
    return get_provider()


def style_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Style Lock step (palette + style sheet extraction)."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.steps.style_lock import do_style_lock

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        check_cancel(cancel)

        do_style_lock(catalog, _sink(job))
        check_cancel(cancel)
        return 0.0

    return fn


def generate_one_adapter(
    category: str,
    asset_id: str,
    *,
    prompt_override: str | None = None,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for regenerating exactly one cell. Auto-promotes to live.

    prompt_override: if provided, used in place of the catalog prompt for
    this generation. Stored on the new history entries' sidecar so the
    side panel can show 'this is the prompt that made this art'.
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.ops import (
            draw_cell,
            spec_for_centerpiece,
            spec_for_panel,
            spec_for_space,
        )

        catalog = _load_catalog()
        if category != "centerpiece":
            _validate_mockup_or_die(catalog)
        provider = _resolve_provider(pixellab_key, openai_key)
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

    return fn


def generate_missing_adapter(
    category: str,
    *,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for "generate every cell of this category that has no live asset."

    One umbrella job with internal N-of-M progress. Categories:
      - "spaces"      → generate every space design that's missing a live asset
      - "panels"      → generate every functional panel that's missing one
      - "centerpiece" → only one cell, but kept here for adapter symmetry
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.ops import (
            generate_centerpiece,
            generate_missing_panels,
            generate_missing_spaces,
        )

        catalog = _load_catalog()
        if category != "centerpiece":
            _validate_mockup_or_die(catalog)
        provider = _resolve_provider(pixellab_key, openai_key)
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

    return fn


def generate_all_adapter(
    *,
    pixellab_key: str | None = None,
    openai_key: str | None = None,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for "generate every empty space AND every empty UI panel."

    Runs spaces first then panels, each as a sub-pass, so the job progress
    reflects the combined total of missing assets.
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.ops import generate_missing_panels, generate_missing_spaces

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        provider = _resolve_provider(pixellab_key, openai_key)
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

    return fn


def clean_one_adapter(
    category: str, asset_id: str,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for re-cleaning the live image of one cell. Free, fast.

    Re-runs palette quantize + grid-snap on the current live PNG, pushes
    the result to history with operation=clean, and promotes it as the
    new live. Useful when the palette changed after generation.
    """

    def fn(job: Job, cancel: threading.Event) -> float:
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

    return fn


# ────────────────────────── adapters: board-level (states / preview / export) ──────────────────────────


def states_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Active-States step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.steps.states import do_states

        catalog = _load_catalog()
        do_states(catalog, _sink(job))
        check_cancel(cancel)
        return 0.0

    return fn


def preview_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Composite Preview step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.steps.compositor import do_preview

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        do_preview(catalog, _sink(job))
        check_cancel(cancel)
        return 0.0

    return fn


def export_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Export step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.steps.export import do_export

        catalog = _load_catalog()
        do_export(catalog, _sink(job))
        check_cancel(cancel)
        return 0.0

    return fn


# ────────────────────────── adapter: centerpiece masked refine ──────────────────────────


def refine_adapter(
    *,
    prompt_hint: str,
    mask_b64: str,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for centerpiece masked refinement (one inpaint call against
    the current live centerpiece image).

    Writes the result into workspace/refinements/ as `centerpiece_vNN.png`.
    Refinements are reviewed in their own gallery and adopted manually —
    they are intentionally NOT auto-promoted to live (a refine is a
    suggestion, not a commit).
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        import base64
        import io

        from PIL import Image

        from boardfactory import assets as bf_assets, config

        live = bf_assets.live_path("centerpiece", "centerpiece")
        if not live.exists():
            raise RuntimeError(
                "No live centerpiece yet — generate one before refining."
            )

        catalog = _load_catalog()
        check_cancel(cancel)

        full_prompt = ". ".join(p for p in [
            catalog.style.prompt,
            catalog.centerpiece.prompt,
            prompt_hint,
        ] if p)

        src_bytes = live.read_bytes()
        mask_bytes = base64.b64decode(mask_b64.split(",", 1)[-1])

        src_img = Image.open(io.BytesIO(src_bytes)).convert("RGBA")
        mask = (
            Image.open(io.BytesIO(mask_bytes))
            .convert("L")
            .resize(src_img.size, Image.NEAREST)
        )
        mask = mask.point(lambda v: 255 if v > 32 else 0)
        mask_buf = io.BytesIO()
        mask.save(mask_buf, format="PNG")
        mask_bytes = mask_buf.getvalue()

        check_cancel(cancel)
        sink = _sink(job)
        sink.start("refine centerpiece", total=1)
        sink.log(f"hint: {prompt_hint or '(none)'}")

        from server import _palette_for_provider, _pixellab_inpaint
        result_bytes = _pixellab_inpaint(
            prompt=full_prompt,
            source_image=src_bytes,
            mask_image=mask_bytes,
            palette=_palette_for_provider(),
        )

        config.REFINEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        n = len(list(config.REFINEMENTS_DIR.glob("centerpiece_v*.png"))) + 1
        out = config.REFINEMENTS_DIR / f"centerpiece_v{n:02d}.png"
        out.write_bytes(result_bytes)
        sink.step(out.name)
        sink.log(f"wrote refinement: {out.name}")

        cost = estimate_refine()
        cost_ledger.record("refine.centerpiece", None, 1, cost)
        return cost

    return fn

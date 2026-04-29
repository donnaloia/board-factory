"""Adapters that bind pipeline functions to the Job runner.

Each adapter:
1. Builds a worker function fn(job, cancel) -> cost_actual
2. Inside fn:
   - validates inputs (catalog exists, mockup OK, etc.) and raises early
   - runs the underlying pipeline step with rich-console output captured
     into job.log via capture_console_for_job
   - records cost into the ledger when the step talks to a paid provider
   - returns the realized cost

The web layer doesn't import boardfactory directly; it goes through here.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from jobs import Job, JobCancelled, capture_console_for_job, check_cancel
import cost_ledger


# ────────────────────────── catalog & provider ──────────────────────────


def _load_catalog():
    from boardfactory import config
    from boardfactory.schemas import Catalog

    if not config.CATALOG_PATH.exists():
        raise RuntimeError(
            f"Catalog not found at {config.CATALOG_PATH}. "
            f"Copy catalog/example.yml to catalog/board.yml first."
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


# ────────────────────────── cost estimators ──────────────────────────


def estimate_style() -> float:
    return 0.0  # local-only, no provider call


def estimate_generate(category: str) -> float:
    """Roughly estimate cost in USD for a full category generation."""
    from boardfactory import config

    if category == "spaces":
        return float(config.SPACE_CANDIDATES) * 0.015 * 8       # designs vary, ~8 designs
    if category == "panels":
        return float(config.PANEL_CANDIDATES) * 0.015 * 12      # 12 panels
    if category == "centerpiece":
        return float(config.CENTERPIECE_CANDIDATES) * 0.022     # higher per call
    return 0.0


def estimate_generate_one(category: str, target: str | None = None) -> float:
    """Estimate a single design / panel / centerpiece regen."""
    from boardfactory import config

    if category == "centerpiece":
        return float(config.CENTERPIECE_CANDIDATES) * 0.022
    if category == "panels":
        return float(config.PANEL_CANDIDATES) * 0.015
    if category == "spaces":
        return float(config.SPACE_CANDIDATES) * 0.015
    return 0.0


def estimate_refine() -> float:
    return 0.022  # one inpaint call


def estimate_regen_one(category: str, asset_id: str | None = None) -> float:
    """Cost of regenerating one cell (one design / panel / centerpiece)."""
    from boardfactory import config

    if category == "spaces":
        return float(config.SPACE_CANDIDATES) * 0.015
    if category == "panels":
        return float(config.PANEL_CANDIDATES) * 0.015
    if category == "centerpiece":
        return float(config.CENTERPIECE_CANDIDATES) * 0.022
    return 0.0


# ────────────────────────── adapters ──────────────────────────


def style_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Style Lock step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.style_lock import do_style_lock

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        check_cancel(cancel)

        run = RunStats(label="style")
        with capture_console_for_job(job):
            do_style_lock(run, catalog)
        check_cancel(cancel)
        return 0.0

    return fn


def generate_adapter(category: str) -> Callable[[Job, threading.Event], float]:
    """Adapter for a full-category generate (spaces / panels / centerpiece)."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.providers import get_provider
        from boardfactory.steps.generate import (
            do_generate_centerpiece,
            do_generate_panels,
            do_generate_spaces,
        )

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        provider = get_provider()
        check_cancel(cancel)

        run = RunStats(label=f"generate-{category}")
        with capture_console_for_job(job):
            if category == "spaces":
                spent = do_generate_spaces(run, catalog, provider)
            elif category == "panels":
                spent = do_generate_panels(run, catalog, provider)
            elif category == "centerpiece":
                spent = do_generate_centerpiece(run, catalog, provider)
            else:
                raise RuntimeError(f"Unknown generate category: {category}")
        check_cancel(cancel)
        cost_ledger.record(f"generate.{category}", None, 1, spent)
        return spent

    return fn


def generate_spaces_adapter(
    design_ids: list[str],
) -> Callable[[Job, threading.Event], float]:
    """Adapter for generating a selected set of space designs."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.providers import get_provider
        from boardfactory.steps.generate import do_generate_spaces

        if not design_ids:
            job.log.append("no missing spaces to generate")
            return 0.0

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        provider = get_provider()
        check_cancel(cancel)

        run = RunStats(label="generate-spaces")
        with capture_console_for_job(job):
            spent = do_generate_spaces(run, catalog, provider, design_ids=design_ids)
        check_cancel(cancel)
        cost_ledger.record("generate.spaces", None, len(design_ids), spent)
        return spent

    return fn


def cleanup_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Cleanup step (palette quantize + grid snap)."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.cleanup import do_cleanup

        run = RunStats(label="cleanup")
        with capture_console_for_job(job):
            do_cleanup(run)
        check_cancel(cancel)
        return 0.0

    return fn


def states_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the State Generation step (active variants)."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.states import do_states

        catalog = _load_catalog()
        run = RunStats(label="states")
        with capture_console_for_job(job):
            do_states(run, catalog)
        check_cancel(cancel)
        return 0.0

    return fn


def preview_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Composite Preview step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.compositor import do_preview

        catalog = _load_catalog()
        _validate_mockup_or_die(catalog)
        run = RunStats(label="preview")
        with capture_console_for_job(job):
            do_preview(run, catalog)
        check_cancel(cancel)
        return 0.0

    return fn


def export_adapter() -> Callable[[Job, threading.Event], float]:
    """Adapter for the Export step."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.export import do_export

        catalog = _load_catalog()
        run = RunStats(label="export")
        with capture_console_for_job(job):
            do_export(run, catalog)
        check_cancel(cancel)
        return 0.0

    return fn


def regen_one_adapter(
    category: str,
    asset_id: str,
    *,
    prompt_override: str | None = None,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for regenerating exactly one cell. Auto-promotes to live.

    prompt_override: if provided, used instead of the catalog prompt for this
    one generation. Recorded in each new history entry's metadata sidecar.
    """

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.providers import get_provider
        from boardfactory.steps.regen_one import (
            do_regen_centerpiece,
            do_regen_panel,
            do_regen_space,
        )

        catalog = _load_catalog()
        if category != "centerpiece":
            _validate_mockup_or_die(catalog)
        provider = get_provider()
        check_cancel(cancel)

        run = RunStats(label=f"regen-{category}:{asset_id}")
        with capture_console_for_job(job):
            if category == "spaces":
                result = do_regen_space(run, catalog, asset_id, provider,
                                        prompt_override=prompt_override)
            elif category == "panels":
                result = do_regen_panel(run, catalog, asset_id, provider,
                                        prompt_override=prompt_override)
            elif category == "centerpiece":
                result = do_regen_centerpiece(run, catalog, provider,
                                              prompt_override=prompt_override)
            else:
                raise RuntimeError(f"Unknown category: {category}")
        check_cancel(cancel)
        cost_ledger.record(f"regen.{category}", asset_id, 1, result.spent)
        job.log.append(
            f"promoted: {result.promoted or '(none)'}  history+={len(result.new_history)}"
        )
        return result.spent

    return fn


def clean_one_adapter(
    category: str, asset_id: str
) -> Callable[[Job, threading.Event], float]:
    """Adapter for re-cleaning the live image of one cell. Free, fast."""

    def fn(job: Job, cancel: threading.Event) -> float:
        from boardfactory.progress import RunStats
        from boardfactory.steps.regen_one import do_clean_one

        check_cancel(cancel)
        run = RunStats(label=f"clean:{category}:{asset_id}")
        with capture_console_for_job(job):
            result = do_clean_one(run, category, asset_id)
        check_cancel(cancel)
        job.log.append(
            f"promoted: {result.promoted or '(none)'}  cleaned and pushed to history"
        )
        return 0.0

    return fn


def refine_adapter(
    *,
    prompt_hint: str,
    mask_b64: str,
) -> Callable[[Job, threading.Event], float]:
    """Adapter for centerpiece masked refinement (one inpaint call)."""

    def fn(job: Job, cancel: threading.Event) -> float:
        import base64
        import io
        from PIL import Image
        from boardfactory import config

        # Load current centerpiece.
        approved = config.APPROVED_DIR / "centerpiece.png"
        if not approved.exists():
            raise RuntimeError("No approved centerpiece yet — approve a candidate first.")

        catalog = _load_catalog()
        check_cancel(cancel)

        full_prompt = ". ".join(p for p in [
            catalog.style.prompt,
            catalog.centerpiece.prompt,
            prompt_hint,
        ] if p)

        src_bytes = approved.read_bytes()
        mask_bytes = base64.b64decode(mask_b64.split(",", 1)[-1])

        src_img = Image.open(io.BytesIO(src_bytes)).convert("RGBA")
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(src_img.size, Image.NEAREST)
        mask = mask.point(lambda v: 255 if v > 32 else 0)
        mask_buf = io.BytesIO()
        mask.save(mask_buf, format="PNG")
        mask_bytes = mask_buf.getvalue()

        check_cancel(cancel)
        job.log.append(f"refining centerpiece with hint: {prompt_hint or '(none)'}")

        # Use the same lightweight inpaint client as the existing /centerpiece/refine route.
        from server import _pixellab_inpaint, _palette_for_provider
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
        job.log.append(f"wrote refinement: {out.name}")

        cost = estimate_refine()
        cost_ledger.record("refine.centerpiece", None, 1, cost)
        return cost

    return fn

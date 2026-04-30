"""Loops over `draw_cell` for "generate everything" buttons.

Each function:

  1. Builds a list of DrawSpecs (one per asset that still needs art)
  2. Tells the sink it's starting an outer pass with total = len(specs)
  3. Loops `draw_cell`, advancing the outer sink between calls
  4. Returns one `DrawResult` per spec (in catalog order)

The sink sees a flat sequence of "asset N/M" steps. The web app's
JobProgressSink turns those into job.progress + log lines so the user
sees N/M panels filling in live in the job tray.

"Missing" = no live asset. A cell with raw candidates from an abandoned
earlier run still counts as missing — until something is on the board,
the artist hasn't accepted anything for that cell. This matches the
semantics in `services/review-ui/server.py:_has_generated_asset`.
"""

from __future__ import annotations

import time

from .. import assets
from ..providers import PixelArtProvider
from ..schemas import Catalog
from .draw_cell import (
    DrawResult,
    draw_cell,
    spec_for_centerpiece,
    spec_for_panel,
    spec_for_space,
)
from .progress import ProgressSink


# ────────────────────────── inner sink shim ──────────────────────────


class _InnerSink:
    """Wraps a ProgressSink so a `draw_cell` call inside an orchestrator loop
    can't call `start()` (which would reset the outer asset-level bar).

    `start` becomes a `log`, `step` becomes a `log` with a smaller indent so
    per-candidate notes still appear in the job log without disturbing the
    outer `1/12 panels` headline.
    """

    def __init__(self, outer: ProgressSink, label_prefix: str = ""):
        self._outer = outer
        self._prefix = label_prefix

    def start(self, label: str, total: int) -> None:
        # Don't reset the outer bar — emit a log line instead so the job
        # tray still shows what's happening per-asset.
        self._outer.log(f"{self._prefix}{label}  (n={total})")

    def step(self, label: str, advance: int = 1) -> None:
        # Inner candidate steps don't move the outer bar; they're just notes.
        self._outer.log(f"{self._prefix}  {label}")

    def log(self, msg: str) -> None:
        self._outer.log(f"{self._prefix}{msg}")


# ────────────────────────── helpers ──────────────────────────


def _missing_space_design_ids(catalog: Catalog) -> list[str]:
    return [
        d.id for d in catalog.all_space_designs()
        if not assets.has_live("spaces", d.id)
    ]


def _missing_panel_ids(catalog: Catalog) -> list[str]:
    return [
        p.id for p in catalog.all_panels()
        if not assets.has_live("panels", p.id)
    ]


# ────────────────────────── entrypoints ──────────────────────────


def generate_missing_spaces(
    catalog: Catalog,
    provider: PixelArtProvider,
    sink: ProgressSink,
) -> list[DrawResult]:
    """Run draw_cell once per space design that has no live asset yet.

    Returns one DrawResult per attempt (in catalog order). Failures don't
    stop the loop — they appear in the result list with empty
    history_filenames and are logged via the sink.
    """
    missing = _missing_space_design_ids(catalog)
    if not missing:
        sink.log("no missing spaces")
        return []

    sink.start(f"generate missing spaces ({len(missing)})", total=len(missing))
    return _loop(missing, spec_for_space, catalog, provider, sink)


def generate_missing_panels(
    catalog: Catalog,
    provider: PixelArtProvider,
    sink: ProgressSink,
) -> list[DrawResult]:
    """Run draw_cell once per functional panel that has no live asset yet."""
    missing = _missing_panel_ids(catalog)
    if not missing:
        sink.log("no missing panels")
        return []

    sink.start(f"generate missing panels ({len(missing)})", total=len(missing))
    return _loop(missing, spec_for_panel, catalog, provider, sink)


def generate_centerpiece(
    catalog: Catalog,
    provider: PixelArtProvider,
    sink: ProgressSink,
) -> DrawResult:
    """Run draw_cell once for the centerpiece. Always one item.

    Wrapping a single-item case in the same orchestrator shape keeps the
    web app's adapter symmetry — every "generate" button hits an
    orchestrator, never `draw_cell` directly.
    """
    sink.start("generate centerpiece", total=1)
    spec = spec_for_centerpiece(catalog)
    result = draw_cell(spec, provider, _InnerSink(sink))
    sink.step("centerpiece")
    return result


# ────────────────────────── shared loop ──────────────────────────


def _loop(
    asset_ids: list[str],
    spec_builder,
    catalog: Catalog,
    provider: PixelArtProvider,
    sink: ProgressSink,
) -> list[DrawResult]:
    """Build a spec for each asset id, run draw_cell, collect results.

    The outer sink owns the asset-level bar (`sink.start` was already called
    by the caller). Each `draw_cell` is given an `_InnerSink` so its own
    `start()` becomes a log line instead of resetting the bar. After each
    successful draw, the outer bar advances by one — the granularity the
    user actually cares about ("3/12 panels").
    """
    results: list[DrawResult] = []
    inner = _InnerSink(sink)
    for i, aid in enumerate(asset_ids):
        try:
            spec = spec_builder(catalog, aid)
        except Exception as e:
            sink.log(f"FAIL build spec for {aid}: {e}")
            continue

        try:
            result = draw_cell(spec, provider, inner)
        except Exception as e:
            sink.log(f"FAIL draw_cell for {aid}: {e}")
            sink.step(aid)
            continue

        results.append(result)
        sink.step(aid)

        # Brief pause between requests to stay inside OpenAI rate limits.
        # Skipped after the last item so the job doesn't stall at 100%.
        if i < len(asset_ids) - 1:
            time.sleep(1.5)

    return results

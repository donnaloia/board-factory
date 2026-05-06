"""Approach D — rewrite panel interiors after a new house frame is adopted.

Sourced from the customization plan's "baked-in chrome" section: when
the user commits a new ``FrameInstance``, every functional panel that
the catalog enables for frames may have **old chrome baked into its
pixels**. Pasting the new rim on top would produce double borders. We
fix this once at commit time by inpainting the panel interior, leaving
the rim region preserved (PixelLab / OpenAI inpaint with a hole-shaped
mask), and rolling the previous live image into history with an
explicit tag so the user can roll back if a regenerated panel looks
worse than the original.

Per-panel work scope:

  1. Snapshot the current live PNG into history with operation
     ``OP_FRAME_REWORK_PRE`` so the user can revert.
  2. Build an inpaint ``DrawSpec`` whose mask is the *hole* (i.e. the
     interior region only). The new rim survives untouched.
  3. Run ``draw_cell`` to produce N candidates. The first one is
     promoted to live; the rest land in history under the standard
     ``OP_REGEN`` operation.

The function returns a ``ReapplyPanelResult`` per call so the
job-runner adapter can stream progress (one panel at a time) and
record the realized cost.

Centerpiece + spaces are intentionally NOT included — Approach D's
fan-out is panels-only by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import assets, frames
from ..providers import PixelArtProvider
from ..schemas import Catalog
from .draw_cell import DrawResult, draw_cell, spec_for_panel
from .progress import ProgressSink


# Operation tag stamped on the snapshot of the panel's previous live PNG
# before its interior is rewritten. Visible in the side panel's history
# strip so the user can spot pre/post-frame versions and revert.
OP_FRAME_REWORK_PRE = "frame_rework_pre"


@dataclass(frozen=True)
class ReapplyPanelResult:
    panel_id: str
    promoted_filename: str | None
    history_filenames: list[str]
    spent_usd: float
    skipped: bool                 # True when the panel had no live to start with
    error: str | None = None


def reapply_to_panel(
    catalog: Catalog,
    panel_id: str,
    provider: PixelArtProvider,
    sink: ProgressSink,
    *,
    prompt_override: str | None = None,
) -> ReapplyPanelResult:
    """Rewrite one panel's interior under the active house frame.

    Reuses ``spec_for_panel`` because that builder already has the
    "frame on AND live exists -> inpaint" branch (see draw_cell.py
    lines around the ``use_inpaint`` decision); we just enforce the
    branch by ensuring the live exists, then snapshot it before the
    rewrite so the user retains a revert path.

    Failure mode: if the provider call inside ``draw_cell`` fails, we
    still return a result with ``promoted_filename=None`` and an error
    string rather than raising — Approach D should keep going across
    other panels even if one fails.
    """
    if not assets.has_live("panels", panel_id):
        sink.log(f"skip panel:{panel_id} (no live to rework)")
        sink.step(f"panel:{panel_id} (skipped)")
        return ReapplyPanelResult(
            panel_id=panel_id,
            promoted_filename=None,
            history_filenames=[],
            spent_usd=0.0,
            skipped=True,
        )

    if not frames.has_house_frame():
        raise RuntimeError(
            "reapply_to_panel called but no house frame is on disk; "
            "the Atelier should have committed the FrameInstance first."
        )

    # 1. Snapshot the current live with a distinctive op tag so the user
    #    can find the "before" version in history and roll back.
    live_path = assets.live_path("panels", panel_id)
    pre_bytes = live_path.read_bytes()
    assets.push_to_history(
        "panels",
        panel_id,
        pre_bytes,
        operation=OP_FRAME_REWORK_PRE,
        prompt=None,
        extras={"reason": "frame rework — preserved before rim re-apply"},
    )

    # 2. Build the inpaint spec. spec_for_panel's "frame on + live exists"
    #    path already returns mode="inpaint" with mask_bytes set to the
    #    interior mask scaled to this panel's size — exactly what we want.
    spec = spec_for_panel(catalog, panel_id, prompt_override=prompt_override)
    if spec.mode != "inpaint":
        # Defensive: if the catalog says frames are on but spec_for_panel
        # picked img2img anyway (e.g. live disappeared between has_live and
        # spec_for_panel reading config), bail with a useful error rather
        # than burning a generation on the wrong mode.
        return ReapplyPanelResult(
            panel_id=panel_id,
            promoted_filename=None,
            history_filenames=[],
            spent_usd=0.0,
            skipped=False,
            error=(
                f"reapply_to_panel: spec_for_panel returned mode={spec.mode!r}, "
                "expected 'inpaint'. Check catalog.frame.enabled and "
                "catalog.frame.apply_to_panels."
            ),
        )

    try:
        result: DrawResult = draw_cell(spec, provider, sink)
    except Exception as e:  # noqa: BLE001 — we want to keep batching.
        return ReapplyPanelResult(
            panel_id=panel_id,
            promoted_filename=None,
            history_filenames=[],
            spent_usd=0.0,
            skipped=False,
            error=f"{type(e).__name__}: {e}",
        )

    return ReapplyPanelResult(
        panel_id=panel_id,
        promoted_filename=result.promoted_filename,
        history_filenames=list(result.history_filenames),
        spent_usd=float(result.spent_usd),
        skipped=False,
    )


def applicable_panels(catalog: Catalog) -> list[str]:
    """Return the panel ids in scope for Approach D.

    The customization plan is explicit: Approach D fans out across
    *every functional panel asset* when ``apply_to_panels`` is true,
    not "every cell on the board" — perimeter spaces are not in scope.
    Centerpiece is also excluded (it doesn't carry a frame).
    """
    if not catalog.frame.apply_to_panels:
        return []
    return [p.id for p in catalog.all_panels()]


def cancellation_friendly_iter(panel_ids: list[str], cancel_check):
    """Yield panel ids, calling ``cancel_check()`` between each.

    Caller passes a no-arg callable that raises if the job has been
    cancelled. Sized intentionally tiny so the worker decides where to
    stop without us hard-coding a job-runner dependency in this module.
    """
    for pid in panel_ids:
        cancel_check()
        yield pid


def estimate_reapply_cost(
    catalog: Catalog,
    provider: PixelArtProvider,
    *,
    candidates_per_panel: int = 1,
) -> float:
    """USD estimate for rewriting every applicable panel under the new frame.

    Multiplied across the full panel inventory because Approach D's
    contract is "every panel in scope, atomically", with cancellation as
    the user's escape hatch rather than partial dry-runs.
    """
    n = len(applicable_panels(catalog))
    if n == 0:
        return 0.0
    # Use a representative panel size for the cost-per-call estimate;
    # OpenAI / PixelLab don't bill per-pixel below their tile floor.
    sample = next(iter(catalog.all_panels()), None)
    size = sample.target_size if sample else (256, 256)
    per_call = provider.cost_estimate(size, candidates_per_panel)
    return float(per_call) * n


__all__ = [
    "OP_FRAME_REWORK_PRE",
    "ReapplyPanelResult",
    "reapply_to_panel",
    "applicable_panels",
    "estimate_reapply_cost",
    "cancellation_friendly_iter",
]

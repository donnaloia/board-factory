"""Atomic art-generation operations the web app drives.

The web app talks to this module exclusively when it needs to make art:

- `draw_cell(spec, provider, sink)` is the one-and-only generate primitive.
  It runs the appropriate provider call (txt2img / img2img / inpaint based
  on `spec.mode`), cleans each candidate inline, pushes everything to the
  per-asset history with a prompt sidecar, and promotes the first candidate
  as live.

- `spec_for_*` builders turn a catalog + asset id into a `DrawSpec`. They
  apply the style prefix, decide inpaint-vs-img2img for panels, and load
  references / palette so callers don't have to.

- `orchestrate.generate_missing_*` loops over many specs, emitting per-asset
  progress events to a `ProgressSink`. This is what the "Generate all
  missing spaces" / "Generate all panels" UI buttons run.
"""

from .progress import ProgressSink, NoopSink
from .draw_cell import (
    DrawMode,
    DrawSpec,
    DrawResult,
    draw_cell,
    spec_for_space,
    spec_for_panel,
    spec_for_centerpiece,
)
from .orchestrate import (
    generate_centerpiece,
    generate_missing_panels,
    generate_missing_spaces,
)

__all__ = [
    "ProgressSink",
    "NoopSink",
    "DrawMode",
    "DrawSpec",
    "DrawResult",
    "draw_cell",
    "spec_for_space",
    "spec_for_panel",
    "spec_for_centerpiece",
    "generate_centerpiece",
    "generate_missing_panels",
    "generate_missing_spaces",
]

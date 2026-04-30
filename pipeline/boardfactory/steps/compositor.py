"""Board Compositor — assemble every live tile onto a board-sized canvas.

Produces two views in `workspace/preview/`:

  - board_idle.png   — every tile in its base state
  - board_active.png — every tile in its active state where one exists

The faded mockup sits behind everything as a backdrop so missing tiles
read as obviously empty against the intended layout. Functional panels
get the house frame composited on top when the frame system is active.

After the live/history refactor, this only ever reads from `live/`. The
legacy `approved/` fallback was removed when the pipeline became web-only.
"""

from __future__ import annotations

from PIL import Image

from .. import assets, config, frames
from ..geometry import board_canvas, paste_tile
from ..ops.progress import ProgressSink
from ..schemas import Catalog


def do_preview(catalog: Catalog, sink: ProgressSink) -> None:
    idle_canvas = board_canvas(catalog.board_size)
    active_canvas = board_canvas(catalog.board_size)

    # Background is already the solid board colour from board_canvas().

    total = (
        sum(len(d.positions) for d in catalog.all_space_designs())
        + len(catalog.all_panels())
        + 1  # centerpiece
    )

    sink.start("compositing tiles", total=total)
    failures: list[str] = []

    # 2. Board spaces — paste each design at every position it occupies.
    for design in catalog.all_space_designs():
        src = assets.live_path("spaces", design.id)
        if not src.exists():
            sink.log(f"skip space:{design.id} (no live)")
            for _ in design.positions:
                sink.step(design.id)
            failures.append(f"space:{design.id}")
            continue
        tile = Image.open(src).convert("RGBA")
        for ref in design.positions:
            x, y, w, h = catalog.board_spaces.resolve_position(ref)
            paste_tile(idle_canvas, tile, (x, y), (w, h))
            paste_tile(active_canvas, tile, (x, y), (w, h))
            sink.step(f"{design.id}@{ref}")

    # 3. Feature panels — paste, then overlay the house frame if active.
    frame_active_for_panels = (
        catalog.frame.enabled
        and catalog.frame.apply_to_panels
        and frames.has_house_frame()
    )
    for panel in catalog.all_panels():
        src = assets.live_path("panels", panel.id)
        if not src.exists():
            sink.log(f"skip panel:{panel.id} (no live)")
            sink.step(panel.id)
            failures.append(f"panel:{panel.id}")
            continue
        tile = Image.open(src).convert("RGBA")
        pos = (panel.bbox[0], panel.bbox[1])
        tgt_w = panel.bbox[2] - panel.bbox[0]
        tgt_h = panel.bbox[3] - panel.bbox[1]
        paste_tile(idle_canvas, tile, pos, (tgt_w, tgt_h))

        active_path = config.LIVE_DIR / "panels" / f"{panel.id}_active.png"
        active_tile = (
            Image.open(active_path).convert("RGBA") if active_path.exists() else tile
        )
        paste_tile(active_canvas, active_tile, pos, (tgt_w, tgt_h))

        if frame_active_for_panels:
            frame_overlay = frames.compose_house_frame_for((tgt_w, tgt_h))
            if frame_overlay is not None:
                idle_canvas.paste(frame_overlay, pos, frame_overlay)
                active_canvas.paste(frame_overlay, pos, frame_overlay)

        sink.step(f"panel:{panel.id}")

    # 4. Centerpiece.
    cp_src = assets.live_path("centerpiece", "centerpiece")
    if cp_src.exists():
        cp = catalog.centerpiece
        pos = (cp.bbox[0], cp.bbox[1])
        size = (cp.bbox[2] - cp.bbox[0], cp.bbox[3] - cp.bbox[1])
        tile = Image.open(cp_src).convert("RGBA")
        paste_tile(idle_canvas, tile, pos, size)

        cp_active = config.LIVE_DIR / "centerpiece" / "centerpiece_active.png"
        active = (
            Image.open(cp_active).convert("RGBA") if cp_active.exists() else tile
        )
        paste_tile(active_canvas, active, pos, size)
    else:
        sink.log("skip centerpiece (no live)")
        failures.append("centerpiece")
    sink.step("centerpiece")

    idle_path = config.PREVIEW_DIR / "board_idle.png"
    active_path = config.PREVIEW_DIR / "board_active.png"
    idle_path.parent.mkdir(parents=True, exist_ok=True)
    idle_canvas.save(idle_path)
    active_canvas.save(active_path)

    sink.log(f"idle    -> {idle_path}")
    sink.log(f"active  -> {active_path}")
    if failures:
        sink.log(f"composited with {len(failures)} missing tile(s): {', '.join(failures)}")

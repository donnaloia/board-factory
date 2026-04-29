"""Step 7: Board Compositor.

Assembles every approved asset onto a board-sized canvas at its declared
position. Produces two views: idle (every tile in its base state) and active
(every tile in its active state, where one exists).

Used as the final visual coherence check before export — if anything looks
out of place here, fix it in the review UI before exporting.
"""

from __future__ import annotations

from PIL import Image

from .. import assets, config, frames
from ..geometry import board_canvas, paste_tile
from ..progress import RunStats, progress_bar, step
from ..schemas import Catalog


def _resolve_asset(category: str, asset_id: str, legacy: "any") -> "any":
    """Prefer live/<asset_id>.png (new web flow), fall back to approved/<asset_id>.png
    (classic CLI flow)."""
    p = assets.live_path(category, asset_id)
    if p.exists():
        return p
    return legacy


def do_preview(run: RunStats, catalog: Catalog) -> None:
    with step(run, "preview") as s:
        idle_canvas = board_canvas(catalog.board_size)
        active_canvas = board_canvas(catalog.board_size)

        # 1. Background: paste the mockup as a faded backdrop so missing tiles are obvious.
        # Aspect-preserving fit (letterbox) — non-uniform stretching would distort the
        # backdrop relative to the canvas grid and make alignment hard to eyeball.
        mockup_path = config.BOARD_ROOT / catalog.style.reference_image
        if mockup_path.exists():
            mockup = Image.open(mockup_path).convert("RGBA")
            mw, mh = mockup.size
            cw, ch = catalog.board_size
            scale = min(cw / mw, ch / mh)
            scaled = mockup.resize((int(round(mw * scale)), int(round(mh * scale))), Image.LANCZOS)
            faded = Image.eval(scaled, lambda v: v // 4)
            offset = ((cw - faded.size[0]) // 2, (ch - faded.size[1]) // 2)
            idle_canvas.paste(faded, offset)
            active_canvas.paste(faded, offset)

        total = (
            sum(len(d.positions) for d in catalog.all_space_designs())
            + len(catalog.all_panels())
            + 1
        )

        with progress_bar("Compositing tiles", total=total) as bar:
            # 2. Board spaces — paste each design at every position it occupies.
            for design in catalog.all_space_designs():
                src = _resolve_asset("spaces", design.id,
                                     config.APPROVED_DIR / "spaces" / f"{design.id}.png")
                if not src.exists():
                    bar.advance(len(design.positions))
                    s.failures.append(f"space:{design.id} not approved")
                    continue
                tile = Image.open(src).convert("RGBA")
                for ref in design.positions:
                    x, y, w, h = catalog.board_spaces.resolve_position(ref)
                    bar.set_current(f"{design.id} @ {ref}")
                    paste_tile(idle_canvas, tile, (x, y), (w, h))
                    paste_tile(active_canvas, tile, (x, y), (w, h))
                    s.items += 1
                    bar.advance()

            # 3. Feature panels — paste at panel.bbox top-left, then overlay the
            #    house frame (if adopted + enabled in catalog) on top of each.
            frame_active_for_panels = (
                catalog.frame.enabled
                and catalog.frame.apply_to_panels
                and frames.has_house_frame()
            )
            for panel in catalog.all_panels():
                src = _resolve_asset("panels", panel.id,
                                     config.APPROVED_DIR / "panels" / f"{panel.id}.png")
                if not src.exists():
                    bar.advance()
                    s.failures.append(f"panel:{panel.id} not approved")
                    continue
                bar.set_current(f"panel:{panel.id}")
                tile = Image.open(src).convert("RGBA")
                pos = (panel.bbox[0], panel.bbox[1])
                tgt_w = panel.bbox[2] - panel.bbox[0]
                tgt_h = panel.bbox[3] - panel.bbox[1]
                paste_tile(idle_canvas, tile, pos, (tgt_w, tgt_h))

                active_path = config.APPROVED_DIR / "panels" / f"{panel.id}_active.png"
                active_tile = Image.open(active_path).convert("RGBA") if active_path.exists() else tile
                paste_tile(active_canvas, active_tile, pos, (tgt_w, tgt_h))

                if frame_active_for_panels:
                    frame_overlay = frames.compose_house_frame_for((tgt_w, tgt_h))
                    if frame_overlay is not None:
                        idle_canvas.paste(frame_overlay, pos, frame_overlay)
                        active_canvas.paste(frame_overlay, pos, frame_overlay)

                s.items += 1
                bar.advance()

            # 4. Centerpiece.
            cp_path = _resolve_asset("centerpiece", "centerpiece",
                                     config.APPROVED_DIR / "centerpiece.png")
            if cp_path.exists():
                bar.set_current("centerpiece")
                cp = catalog.centerpiece
                pos = (cp.bbox[0], cp.bbox[1])
                size = (cp.bbox[2] - cp.bbox[0], cp.bbox[3] - cp.bbox[1])
                tile = Image.open(cp_path).convert("RGBA")
                paste_tile(idle_canvas, tile, pos, size)

                cp_active = config.APPROVED_DIR / "centerpiece_active.png"
                active = Image.open(cp_active).convert("RGBA") if cp_active.exists() else tile
                paste_tile(active_canvas, active, pos, size)
                s.items += 1
            else:
                s.failures.append("centerpiece not approved")
            bar.advance()

        idle_path = config.PREVIEW_DIR / "board_idle.png"
        active_path = config.PREVIEW_DIR / "board_active.png"
        idle_path.parent.mkdir(parents=True, exist_ok=True)
        idle_canvas.save(idle_path)
        active_canvas.save(active_path)
        s.extras["idle"] = str(idle_path.relative_to(config.REPO_ROOT))
        s.extras["active"] = str(active_path.relative_to(config.REPO_ROOT))

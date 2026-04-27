"""Step 4: Pixel Cleanup.

Walks every generated candidate, applies palette quantization (snap to the
shared palette extracted in step 1) and grid alignment (force hard pixel
boundaries), writes the result to workspace/cleaned/ mirroring the candidates/
folder structure.

This is the step that turns "AI's idea of pixel art" into actual pixel art.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .. import config
from ..geometry import detect_native_scale, grid_snap
from ..palette import load_palette, quantize_to_palette
from ..progress import RunStats, progress_bar, step


def do_cleanup(run: RunStats) -> None:
    pal_path = config.STYLE_DIR / "palette.json"
    if not pal_path.exists():
        raise FileNotFoundError(
            f"Palette not found at {pal_path}. Run `boardfactory style` first."
        )
    palette = load_palette(pal_path)

    candidates: list[Path] = []
    for category in ("spaces", "panels", "centerpiece"):
        cat_dir = config.CANDIDATES_DIR / category
        if cat_dir.exists():
            candidates.extend(p for p in cat_dir.rglob("*.png") if not p.name.startswith("_"))

    with step(run, "cleanup") as s:
        s.extras["palette"] = str(len(palette))
        if not candidates:
            s.extras["note"] = "no candidates to clean"
            return
        with progress_bar("Quantize + grid-snap", total=len(candidates)) as bar:
            for src in candidates:
                rel = src.relative_to(config.CANDIDATES_DIR)
                bar.set_current(str(rel))
                try:
                    img = Image.open(src).convert("RGBA")
                    scale = detect_native_scale(img)
                    snapped = grid_snap(img, scale=scale)
                    cleaned = quantize_to_palette(snapped, palette)
                    out = config.CLEANED_DIR / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    cleaned.save(out)
                    s.items += 1
                except Exception as e:
                    s.failures.append(f"{rel}: {e}")
                    bar.write(f"[red]✗[/red] {rel}: {e}")
                bar.advance()

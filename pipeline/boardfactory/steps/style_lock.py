"""Step 1: Style Lock.

Extracts a shared palette from the user's mockup and writes a style-sheet PNG
that subsequent generation steps pass to the model as a style reference. After
this step, every later generation is conditioned on the same visual contract.
"""

from __future__ import annotations

from PIL import Image

from .. import config
from ..palette import (
    extract_palette,
    render_palette_swatch,
    save_palette,
    stitch_grid,
)
from ..progress import RunStats, console, spinner, step
from ..schemas import Catalog


def do_style_lock(run: RunStats, catalog: Catalog) -> None:
    with step(run, "style-lock") as s:
        ref_path = config.REPO_ROOT / catalog.style.reference_image
        if not ref_path.exists():
            raise FileNotFoundError(f"Style reference image not found: {ref_path}")

        with spinner(f"Extracting {catalog.style.palette_size}-color palette from {ref_path.name}..."):
            palette = extract_palette(ref_path, n=catalog.style.palette_size)

        save_palette(
            palette,
            json_path=config.STYLE_DIR / "palette.json",
            gpl_path=config.STYLE_DIR / "palette.gpl",
        )

        swatch = render_palette_swatch(palette, cell=64, cols=8)
        swatch.save(config.STYLE_DIR / "palette_swatch.png")

        # Style sheet: 4x4 grid of crops from the mockup at panel-typical size,
        # giving the model a visual reference for shading, line weight, and palette.
        ref_img = Image.open(ref_path).convert("RGBA")
        crops = []
        w, h = ref_img.size
        cell = (min(w, h) // 4, min(w, h) // 4)
        for row in range(4):
            for col in range(4):
                x = (col * w) // 4
                y = (row * h) // 4
                crops.append(ref_img.crop((x, y, x + cell[0], y + cell[1])))
        sheet = stitch_grid(crops, cell=cell, cols=4)
        sheet.save(config.STYLE_DIR / "style_sheet.png")

        s.items = len(palette)
        s.extras["palette_size"] = str(len(palette))
        s.extras["reference"] = ref_path.name
        console.print(
            f"   [dim]palette →[/dim] {config.STYLE_DIR / 'palette.json'}\n"
            f"   [dim]swatch  →[/dim] {config.STYLE_DIR / 'palette_swatch.png'}\n"
            f"   [dim]sheet   →[/dim] {config.STYLE_DIR / 'style_sheet.png'}"
        )

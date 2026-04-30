"""Style Lock — extract a shared palette + style sheet from the board mockup.

Every subsequent generation passes the style sheet to the model as a style
reference and the palette as the constraint cleanup quantizes against. After
this step, all generated art on this board sits inside the same visual
contract.

Cheap, local-only, no provider call. Run any time the mockup changes.
"""

from __future__ import annotations

from PIL import Image

from .. import config
from ..ops.progress import ProgressSink
from ..palette import (
    extract_palette,
    render_palette_swatch,
    save_palette,
    stitch_grid,
)
from ..schemas import Catalog


def do_style_lock(catalog: Catalog, sink: ProgressSink) -> None:
    ref_path = config.BOARD_ROOT / catalog.style.reference_image
    if not ref_path.exists():
        raise FileNotFoundError(f"Style reference image not found: {ref_path}")

    sink.start("style-lock", total=3)
    sink.log(
        f"extracting {catalog.style.palette_size}-color palette from {ref_path.name}"
    )
    palette = extract_palette(ref_path, n=catalog.style.palette_size)
    save_palette(
        palette,
        json_path=config.STYLE_DIR / "palette.json",
        gpl_path=config.STYLE_DIR / "palette.gpl",
    )
    sink.step("palette")

    swatch = render_palette_swatch(palette, cell=64, cols=8)
    swatch.save(config.STYLE_DIR / "palette_swatch.png")
    sink.step("swatch")

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
    sink.step("style-sheet")

    sink.log(f"palette  -> {config.STYLE_DIR / 'palette.json'}")
    sink.log(f"swatch   -> {config.STYLE_DIR / 'palette_swatch.png'}")
    sink.log(f"sheet    -> {config.STYLE_DIR / 'style_sheet.png'}")

"""Step 3: Generate (branched by category).

Three sub-steps:
- spaces: batch generation of unique board space designs
- panels: per-panel img2img from cropped mockup region
- centerpiece: img2img with high candidate count for marquee asset

All three share the same palette + style sheet from step 1.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .. import config
from ..geometry import crop_region
from ..palette import load_palette
from ..progress import RunStats, fmt_money, progress_bar, step
from ..providers import PixelArtProvider
from ..providers.pixel.pixellab import png_bytes
from ..schemas import Catalog


def _read_style_assets() -> tuple[bytes | None, list[tuple[int, int, int]] | None]:
    palette = None
    pal_path = config.STYLE_DIR / "palette.json"
    if pal_path.exists():
        palette = load_palette(pal_path)
    style_ref = None
    sheet_path = config.STYLE_DIR / "style_sheet.png"
    if sheet_path.exists():
        style_ref = sheet_path.read_bytes()
    return style_ref, palette


def do_generate_spaces(run: RunStats, catalog: Catalog, provider: PixelArtProvider) -> float:
    style_ref, palette = _read_style_assets()
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    designs = catalog.all_space_designs()
    n = config.SPACE_CANDIDATES
    total_calls = len(designs) * n
    estimated = sum(provider.cost_estimate(catalog.board_spaces.size, n) for _ in designs)
    spent = 0.0

    with step(run, "generate-spaces") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        out_root = config.CANDIDATES_DIR / "spaces"
        with progress_bar(
            f"Spaces ({n} per design, est. {fmt_money(estimated)})",
            total=total_calls,
        ) as bar:
            for design in designs:
                bar.set_current(f"{design.id} [dim]({len(design.positions)} positions)")
                out_dir = out_root / design.id
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    images = provider.generate(
                        prompt=style_prefix + design.prompt,
                        size=catalog.board_spaces.size,
                        n=n,
                        style_reference=style_ref,
                        palette=palette,
                    )
                    for i, png in enumerate(images, start=1):
                        (out_dir / f"v{i:02d}.png").write_bytes(png)
                    spent += provider.cost_estimate(catalog.board_spaces.size, n)
                    s.items += 1
                    bar.advance(n)
                except Exception as e:
                    s.failures.append(f"{design.id}: {e}")
                    bar.write(f"[red]✗[/red] {design.id}: {e}")
                    bar.advance(n)
        s.extras["spent"] = fmt_money(spent)
    return spent


def do_generate_panels(run: RunStats, catalog: Catalog, provider: PixelArtProvider) -> float:
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    _, palette = _read_style_assets()
    panels = catalog.all_panels()
    n = config.PANEL_CANDIDATES
    total_calls = len(panels) * n
    estimated = sum(provider.cost_estimate(p.target_size, n) for p in panels)
    spent = 0.0

    mockup_path = config.REPO_ROOT / catalog.style.reference_image

    with step(run, "generate-panels") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        out_root = config.CANDIDATES_DIR / "panels"
        with progress_bar(
            f"Panels ({n} candidates each, est. {fmt_money(estimated)})",
            total=total_calls,
        ) as bar:
            for panel in panels:
                bar.set_current(panel.id)
                out_dir = out_root / panel.id
                out_dir.mkdir(parents=True, exist_ok=True)
                try:
                    ref_img = crop_region(mockup_path, panel.bbox, panel.target_size)
                    ref_bytes = png_bytes(ref_img)
                    (out_dir / "_reference.png").write_bytes(ref_bytes)

                    images = provider.img2img(
                        prompt=style_prefix + panel.prompt,
                        source_image=ref_bytes,
                        size=panel.target_size,
                        strength=0.8,
                        n=n,
                        palette=palette,
                    )
                    for i, png in enumerate(images, start=1):
                        (out_dir / f"v{i:02d}.png").write_bytes(png)
                    spent += provider.cost_estimate(panel.target_size, n)
                    s.items += 1
                    bar.advance(n)
                except Exception as e:
                    s.failures.append(f"{panel.id}: {e}")
                    bar.write(f"[red]✗[/red] {panel.id}: {e}")
                    bar.advance(n)
        s.extras["spent"] = fmt_money(spent)
    return spent


def do_generate_centerpiece(run: RunStats, catalog: Catalog, provider: PixelArtProvider) -> float:
    style_prefix = catalog.style.prompt + ". " if catalog.style.prompt else ""
    _, palette = _read_style_assets()
    cp = catalog.centerpiece
    n = config.CENTERPIECE_CANDIDATES
    estimated = provider.cost_estimate(cp.target_size, n)
    spent = 0.0

    mockup_path = config.REPO_ROOT / catalog.style.reference_image

    with step(run, "generate-centerpiece") as s:
        s.extras["provider"] = provider.name
        s.extras["estimate"] = fmt_money(estimated)
        out_dir = config.CANDIDATES_DIR / "centerpiece"
        out_dir.mkdir(parents=True, exist_ok=True)
        with progress_bar(
            f"Centerpiece ({n} candidates, est. {fmt_money(estimated)})",
            total=n,
        ) as bar:
            try:
                ref_img = crop_region(mockup_path, cp.bbox, cp.target_size)
                ref_bytes = png_bytes(ref_img)
                (out_dir / "_reference.png").write_bytes(ref_bytes)

                images = provider.img2img(
                    prompt=style_prefix + cp.prompt,
                    source_image=ref_bytes,
                    size=cp.target_size,
                    strength=0.85,
                    n=n,
                    palette=palette,
                )
                for i, png in enumerate(images, start=1):
                    (out_dir / f"v{i:02d}.png").write_bytes(png)
                    bar.set_current(f"v{i:02d}")
                    bar.advance()
                spent += provider.cost_estimate(cp.target_size, n)
                s.items = n
            except Exception as e:
                s.failures.append(f"centerpiece: {e}")
                bar.write(f"[red]✗[/red] centerpiece: {e}")
        s.extras["spent"] = fmt_money(spent)
    return spent

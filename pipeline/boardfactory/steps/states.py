"""Step 6: State generation for approved feature panels.

For each approved panel that has `needs_active: true`, applies a procedural
shader-style transform to produce the active variant. Procedural is chosen over
AI generation because it preserves pixel discipline perfectly while AI breaks it.

Three active kinds are supported:
- glow: brighten + add a subtle red overlay; for tiles that should look "lit"
- pulse: bright outline + saturation boost; for tiles that should pulse rhythmically
- flicker: warmer color shift + slight blur on the brightest pixels; for fire tiles
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter

from .. import config
from ..palette import load_palette, quantize_to_palette
from ..progress import RunStats, progress_bar, step
from ..schemas import Catalog


def _glow(img: Image.Image) -> Image.Image:
    enh = ImageEnhance.Brightness(img.convert("RGBA")).enhance(1.2)
    overlay = Image.new("RGBA", img.size, (255, 60, 60, 60))
    return Image.alpha_composite(enh, overlay)


def _pulse(img: Image.Image) -> Image.Image:
    out = img.convert("RGBA")
    out = ImageEnhance.Brightness(out).enhance(1.15)
    out = ImageEnhance.Color(out).enhance(1.4)
    return out


def _flicker(img: Image.Image) -> Image.Image:
    out = img.convert("RGBA")
    out = ImageEnhance.Color(out).enhance(1.25)
    rgb = out.convert("RGB")
    blurred = rgb.filter(ImageFilter.GaussianBlur(radius=0.7))
    out = Image.merge("RGBA", (*blurred.split(), out.getchannel("A")))
    overlay = Image.new("RGBA", img.size, (255, 140, 40, 35))
    return Image.alpha_composite(out, overlay)


_TRANSFORMS = {"glow": _glow, "pulse": _pulse, "flicker": _flicker}


def do_states(run: RunStats, catalog: Catalog) -> None:
    pal_path = config.STYLE_DIR / "palette.json"
    palette = load_palette(pal_path) if pal_path.exists() else None
    panels = [p for p in catalog.all_panels() if p.needs_active and p.active_kind != "none"]

    centerpiece = catalog.centerpiece
    cp_needs = centerpiece.needs_active and centerpiece.active_kind != "none"
    work = list(panels) + ([("__centerpiece__", centerpiece)] if cp_needs else [])

    with step(run, "states") as s:
        s.extras["panels"] = str(len(panels))
        s.extras["centerpiece"] = "yes" if cp_needs else "no"
        if not work:
            s.extras["note"] = "no active states needed"
            return
        with progress_bar("Building active variants", total=len(work)) as bar:
            for entry in work:
                if isinstance(entry, tuple):
                    asset_id, spec = entry
                    base_path = config.APPROVED_DIR / "centerpiece.png"
                    out_path = config.APPROVED_DIR / "centerpiece_active.png"
                else:
                    spec = entry
                    asset_id = spec.id
                    base_path = config.APPROVED_DIR / "panels" / f"{asset_id}.png"
                    out_path = config.APPROVED_DIR / "panels" / f"{asset_id}_active.png"
                bar.set_current(f"{asset_id} [dim]→ {spec.active_kind}")

                if not base_path.exists():
                    s.failures.append(f"{asset_id}: base not approved at {base_path.name}")
                    bar.write(f"[red]✗[/red] {asset_id}: no approved base")
                    bar.advance()
                    continue
                try:
                    fn = _TRANSFORMS[spec.active_kind]
                    img = Image.open(base_path).convert("RGBA")
                    transformed = fn(img)
                    if palette:
                        transformed = quantize_to_palette(transformed, palette)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    transformed.save(out_path)
                    s.items += 1
                except Exception as e:
                    s.failures.append(f"{asset_id}: {e}")
                    bar.write(f"[red]✗[/red] {asset_id}: {e}")
                bar.advance()

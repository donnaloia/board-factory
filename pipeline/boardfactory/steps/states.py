"""Active-state generation for live tiles.

For each tile (panels + centerpiece) flagged with `needs_active=True`, apply
a procedural shader-style transform to produce its active variant. We keep
this procedural rather than asking the AI to generate variants because:

- Procedural preserves the pixel grid perfectly. AI breaks it.
- Procedural is deterministic and free.
- The active-vs-idle delta is a stylistic uplift (glow / pulse / flicker),
  not a structural redesign — exactly what filters are good at.

Reads the live image for each tile, writes the active variant alongside as
`<id>_active.png` in `live/<category>/`. The compositor + exporter pick it
up automatically next time they run.
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter

from .. import assets, config
from ..ops.progress import ProgressSink
from ..palette import load_palette, quantize_to_palette
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


def _active_path(category: str, asset_id: str):
    """Where the active variant for this tile lives on disk."""
    if category == "centerpiece":
        return config.LIVE_DIR / "centerpiece" / "centerpiece_active.png"
    return config.LIVE_DIR / category / f"{asset_id}_active.png"


def do_states(catalog: Catalog, sink: ProgressSink) -> None:
    pal_path = config.STYLE_DIR / "palette.json"
    palette = load_palette(pal_path) if pal_path.exists() else None

    panels = [p for p in catalog.all_panels()
              if p.needs_active and p.active_kind != "none"]
    cp = catalog.centerpiece
    cp_needs = cp.needs_active and cp.active_kind != "none"

    work: list[tuple[str, str, str]] = []  # (category, asset_id, active_kind)
    for p in panels:
        work.append(("panels", p.id, p.active_kind))
    if cp_needs:
        work.append(("centerpiece", "centerpiece", cp.active_kind))

    if not work:
        sink.log("no active states needed")
        return

    sink.start("build active states", total=len(work))
    failures: list[str] = []
    for category, asset_id, kind in work:
        base_path = assets.live_path(category, asset_id)
        out_path = _active_path(category, asset_id)
        label = f"{asset_id} -> {kind}"

        if not base_path.exists():
            failures.append(f"{asset_id}: no live image to derive active from")
            sink.log(f"FAIL {label}: no live image at {base_path.name}")
            sink.step(asset_id)
            continue

        try:
            fn = _TRANSFORMS[kind]
            img = Image.open(base_path).convert("RGBA")
            transformed = fn(img)
            if palette:
                transformed = quantize_to_palette(transformed, palette)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            transformed.save(out_path)
            sink.step(label)
        except Exception as e:
            failures.append(f"{asset_id}: {e}")
            sink.log(f"FAIL {label}: {e}")
            sink.step(asset_id)

    if failures:
        sink.log(f"states completed with {len(failures)} failure(s)")

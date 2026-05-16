"""Frame canvas registration.

Takes any input image and fits it to the exact token canvas
(``canvas_w × canvas_h``) by:

1. Converting to RGBA.
2. Scaling to fit within the canvas while preserving aspect ratio.
3. Centring on a transparent canvas.

The output is always a new ``canvas_w × canvas_h`` RGBA image.
"""

from __future__ import annotations

from PIL import Image


def register_to_canvas(
    img: Image.Image,
    canvas_w: int,
    canvas_h: int,
) -> Image.Image:
    """Return a new ``canvas_w × canvas_h`` RGBA image with ``img`` fitted inside."""
    rgba = img.convert("RGBA")
    iw, ih = rgba.size

    # Scale to fit, preserving aspect ratio
    scale = min(canvas_w / iw, canvas_h / ih)
    new_w = max(1, int(round(iw * scale)))
    new_h = max(1, int(round(ih * scale)))
    scaled = rgba.resize((new_w, new_h), Image.LANCZOS)

    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    off_x = (canvas_w - new_w) // 2
    off_y = (canvas_h - new_h) // 2
    out.paste(scaled, (off_x, off_y), scaled)
    return out


def alpha_bbox_height(img: Image.Image) -> int:
    """Height of the smallest axis-aligned box covering opaque pixels (or ``0``)."""
    bb = img.convert("RGBA").split()[3].getbbox()
    if bb is None:
        return 0
    return bb[3] - bb[1]


def normalize_character_scale_to_reference(
    img: Image.Image,
    ref_bbox_height: int,
    *,
    min_scale: float = 0.55,
    max_scale: float = 1.85,
) -> Image.Image:
    """Uniform-scale ``img`` so opaque bbox height matches ``ref_bbox_height``.

    Image models often drift perceived character size between frames even when the
    raster is later cropped to a fixed canvas; matching bbox height to the
    canonical reference keeps silhouette scale stable across a clip.

    Resampling is nearest-neighbour to preserve pixel-art edges.
    """
    if ref_bbox_height < 4:
        return img.convert("RGBA")

    rgba = img.convert("RGBA")
    bbox = rgba.split()[3].getbbox()
    if bbox is None:
        return rgba

    h = bbox[3] - bbox[1]
    if h < 4:
        return rgba

    scale = ref_bbox_height / float(h)
    scale = max(min_scale, min(max_scale, scale))
    if abs(scale - 1.0) < 1e-5:
        return rgba

    nw = max(1, int(round(rgba.width * scale)))
    nh = max(1, int(round(rgba.height * scale)))
    return rgba.resize((nw, nh), Image.NEAREST)

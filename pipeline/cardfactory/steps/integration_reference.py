"""Source image for single-pass integrated card inpaint (frame chrome added in post)."""

from __future__ import annotations

from PIL import Image

from ..config import SINGLE_PASS_ART_PLACEHOLDER_ALPHA
from .stats_plate import average_opaque_frame_rgb_under_mask


def build_single_pass_inpaint_source(
    frame_img: Image.Image,
    canvas: tuple[int, int],
    interior_mask: Image.Image,
    *,
    art_placeholder_alpha: int | None = None,
    art_darken: int = 12,
) -> Image.Image:
    """``images/edits`` input: one frame-sampled tint under the interior hole, frame on top.

    ``interior_mask`` should match the single-pass edit mask (full inner window ∩
    frame hole) so the reference image does not show a hard art/stats colour
    boundary that encourages two pasted rectangles in the model output.
    """
    w, h = canvas
    art_a = (
        art_placeholder_alpha
        if art_placeholder_alpha is not None
        else SINGLE_PASS_ART_PLACEHOLDER_ALPHA
    )

    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    m = interior_mask.convert("L")

    ra, ga, ba = average_opaque_frame_rgb_under_mask(frame_img, canvas, m)
    ra, ga, ba = max(0, ra - art_darken), max(0, ga - art_darken), max(0, ba - art_darken)
    fill = Image.new("RGBA", (w, h), (ra, ga, ba, min(255, max(0, art_a))))
    base = Image.composite(fill, base, m)

    return Image.alpha_composite(base, frame_img.convert("RGBA"))

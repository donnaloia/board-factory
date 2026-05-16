"""Post-checks after single-pass integrated inpaint + frame composite."""

from __future__ import annotations

from PIL import Image


def rim_matches_frame(
    final_rgba: Image.Image,
    frame_png: Image.Image,
    *,
    frame_alpha_threshold: int = 200,
    max_channel_delta: int = 14,
    max_violation_fraction: float = 0.004,
) -> bool:
    """Return True if pixels where the frame is opaque closely match ``frame_png`` RGB.

    Ignores alpha channel comparison (typography may sit under transparent frame holes).
    Subsamples for speed on large canvases.
    """
    final = final_rgba.convert("RGBA")
    frame = frame_png.convert("RGBA")
    if final.size != frame.size:
        return False

    w, h = final.size
    fpix = final.load()
    frpix = frame.load()
    step = max(1, max(w, h) // 512)

    checked = 0
    bad = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            _, _, _, fa = frpix[x, y]
            if fa < frame_alpha_threshold:
                continue
            checked += 1
            r1, g1, b1, _ = fpix[x, y]
            r2, g2, b2, _ = frpix[x, y]
            if (
                abs(r1 - r2) > max_channel_delta
                or abs(g1 - g2) > max_channel_delta
                or abs(b1 - b2) > max_channel_delta
            ):
                bad += 1

    if checked == 0:
        return True
    return (bad / checked) <= max_violation_fraction

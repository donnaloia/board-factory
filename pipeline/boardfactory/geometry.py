"""Board geometry helpers — crop regions, place tiles on the board."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def crop_region(
    source_image: Path, bbox: tuple[int, int, int, int], target_size: tuple[int, int]
) -> Image.Image:
    """Crop `bbox` from `source_image` and resize to `target_size`.

    Used to extract reference regions from the mockup for img2img conditioning.
    Uses LANCZOS for downscaling so the AI gets the cleanest possible reference.
    """
    img = Image.open(source_image).convert("RGBA")
    cropped = img.crop(bbox)
    if cropped.size != target_size:
        cropped = cropped.resize(target_size, Image.LANCZOS)
    return cropped


def grid_snap(img: Image.Image, scale: int = 1) -> Image.Image:
    """Snap an image to integer pixel boundaries.

    AI generators often produce 'pixel-art-style' output that's actually rendered
    at a higher resolution with antialiased edges. This downscales then upscales
    using nearest-neighbor to enforce hard pixel boundaries.

    `scale` of 1 means 'image is already at native resolution.' For images that
    were generated at 4x (common with PixelLab), pass scale=4.
    """
    if scale == 1:
        return img
    w, h = img.size
    small = img.resize((w // scale, h // scale), Image.LANCZOS)
    return small.resize((w, h), Image.NEAREST)


def detect_native_scale(img: Image.Image, max_check: int = 8) -> int:
    """Heuristic to guess whether an image was rendered at Nx its native pixel resolution.

    Returns the integer scale factor that gives the lowest variance when downsampled
    and upscaled. Useful when AI returns 'pixel-art-style' output at full HD that's
    really only N×N native pixels.
    """
    w, h = img.size
    if w < 64 or h < 64:
        return 1
    best_scale, best_score = 1, float("inf")
    sample = img.convert("RGB")
    for scale in range(1, max_check + 1):
        if w % scale or h % scale:
            continue
        small = sample.resize((w // scale, h // scale), Image.LANCZOS)
        restored = small.resize((w, h), Image.NEAREST)
        score = _frame_variance(sample, restored)
        if score < best_score:
            best_score, best_scale = score, scale
    return best_scale


def _frame_variance(a: Image.Image, b: Image.Image) -> float:
    """Sum of squared per-channel differences between two same-size images."""
    px_a, px_b = a.tobytes(), b.tobytes()
    return sum((x - y) * (x - y) for x, y in zip(px_a, px_b))


def board_canvas(size: tuple[int, int]) -> Image.Image:
    """Create an empty board canvas of the given size with a transparent background."""
    return Image.new("RGBA", size, (0, 0, 0, 0))


def paste_tile(
    canvas: Image.Image,
    tile: Image.Image,
    position: tuple[int, int],
    target_size: tuple[int, int] | None = None,
) -> None:
    """Paste `tile` onto `canvas` at `position` (top-left), optionally resizing first."""
    if target_size and tile.size != target_size:
        tile = tile.resize(target_size, Image.NEAREST)
    canvas.paste(tile, position, tile if tile.mode == "RGBA" else None)

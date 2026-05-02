"""Board geometry helpers — crop regions, place tiles on the board.

Two coordinate systems are in play:

- **Canvas coordinates**: the authoritative space the catalog and spec are
  written in (e.g. 1920 × 1080). Every bbox in the board catalog lives here.
- **Mockup coordinates**: the actual pixel space of the user's mockup file,
  which may not match canvas dimensions (AI-generated mockups rarely hit exact
  target sizes). The pipeline scales canvas-space bboxes into mockup-space at
  crop time so the same catalog works with any mockup size.

The helpers below do that translation. `crop_region` is the only place outside
this module that needs to know the conversion exists.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


# ────────────────────────── coordinate translation ──────────────────────────


def canvas_to_mockup(
    bbox: tuple[int, int, int, int],
    canvas_size: tuple[int, int],
    mockup_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Translate a canvas-space bbox to mockup-space.

    Each axis scales independently, so this works correctly even when the
    mockup has a slightly different aspect ratio from the canvas (the warning
    in `validate_mockup_dimensions` will fire if the drift is meaningful).
    """
    sx = mockup_size[0] / canvas_size[0]
    sy = mockup_size[1] / canvas_size[1]
    x1, y1, x2, y2 = bbox
    # Round to ints at the boundary; clamp inside mockup to handle subpixel drift.
    mx1 = max(0, min(mockup_size[0], int(round(x1 * sx))))
    my1 = max(0, min(mockup_size[1], int(round(y1 * sy))))
    mx2 = max(0, min(mockup_size[0], int(round(x2 * sx))))
    my2 = max(0, min(mockup_size[1], int(round(y2 * sy))))
    return (mx1, my1, mx2, my2)


def mockup_to_canvas(
    bbox: tuple[int, int, int, int],
    mockup_size: tuple[int, int],
    canvas_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Inverse of `canvas_to_mockup`. Useful when authoring catalog from a mockup.

    Not currently called by the pipeline (catalog stays canvas-authoritative)
    but is provided for tools and one-off scripts that want to convert
    mockup-pixel coordinates back to canvas coordinates.
    """
    sx = canvas_size[0] / mockup_size[0]
    sy = canvas_size[1] / mockup_size[1]
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )


# ────────────────────────── mockup validation ──────────────────────────


# Fail loudly if mockup aspect ratio drifts from canvas by more than this fraction.
ASPECT_TOLERANCE = 0.05


class MockupAspectMismatch(ValueError):
    """Raised when a mockup's aspect ratio differs from the canvas by > tolerance."""


def validate_mockup_dimensions(
    mockup_path: Path,
    canvas_size: tuple[int, int],
    *,
    strict: bool = False,
) -> tuple[tuple[int, int], list[str]]:
    """Read mockup dimensions and check them against the catalog's canvas size.

    Returns `(mockup_size, warnings)`. If `strict=True`, raises
    `MockupAspectMismatch` instead of returning a warning when the aspect ratio
    drifts beyond `ASPECT_TOLERANCE`.

    Warnings are collected so the CLI can render them through `rich` instead of
    using stdlib warnings (which would interrupt the progress UI).
    """
    if not mockup_path.exists():
        raise FileNotFoundError(f"Mockup not found: {mockup_path}")

    with Image.open(mockup_path) as img:
        mockup_size = img.size

    warnings: list[str] = []

    canvas_ratio = canvas_size[0] / canvas_size[1]
    mockup_ratio = mockup_size[0] / mockup_size[1]
    drift = abs(mockup_ratio - canvas_ratio) / canvas_ratio

    if drift > ASPECT_TOLERANCE:
        msg = (
            f"Mockup aspect ratio differs from canvas by {drift * 100:.1f}% "
            f"(mockup is {mockup_size[0]}×{mockup_size[1]} = {mockup_ratio:.3f}, "
            f"canvas is {canvas_size[0]}×{canvas_size[1]} = {canvas_ratio:.3f}). "
            f"img2img reference crops will be stretched non-uniformly. "
            f"Consider re-rendering the mockup at the canvas aspect ratio."
        )
        if strict:
            raise MockupAspectMismatch(msg)
        warnings.append(msg)

    if mockup_size != canvas_size:
        warnings.append(
            f"Mockup is {mockup_size[0]}×{mockup_size[1]}, canvas is "
            f"{canvas_size[0]}×{canvas_size[1]}. Pipeline will scale "
            f"catalog bboxes from canvas to mockup coordinates at crop time."
        )

    return mockup_size, warnings


# ────────────────────────── cropping ──────────────────────────


def crop_region(
    source_image: Path,
    bbox: tuple[int, int, int, int],
    target_size: tuple[int, int],
    *,
    canvas_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Crop `bbox` from `source_image` and resize to `target_size`.

    `bbox` is interpreted as **canvas coordinates** when `canvas_size` is
    provided. The function reads the source image's actual size and translates
    the bbox into mockup pixel space before cropping. When `canvas_size` is
    None (legacy/test callers), `bbox` is treated as raw mockup pixel coords.

    Used by `steps/generate.py` to extract per-asset reference regions for
    img2img conditioning. LANCZOS is used for the final resize so the AI gets
    the cleanest possible reference.
    """
    img = Image.open(source_image).convert("RGBA")
    if canvas_size is not None:
        bbox = canvas_to_mockup(bbox, canvas_size, img.size)
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
    """Create an empty board canvas with the board's solid background colour.

    Using a fully opaque background ensures the exported PNG has no transparent
    pixels — empty cells render as the board background rather than transparent,
    so the image looks correct when opened in any viewer or on any background.
    """
    return Image.new("RGBA", size, (13, 14, 16, 255))


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

"""Design Explore operation.

Generates ``CANDIDATE_COUNT`` reference candidates for a token using the
configured provider.  Each candidate is a standalone PNG at the token canvas
size — the user picks one (or uploads their own) and commits it as the
canonical reference via the design-lock flow.

Returns a list of ``Path`` objects for each written candidate PNG.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..config import CANDIDATE_COUNT
from ..providers.base import TokenProvider
from ..steps.bg_remove import remove_background
from .progress import ProgressSink


def design_explore(
    *,
    candidates_dir: Path,
    canvas_w: int,
    canvas_h: int,
    style_sentence: str,
    token_palette: dict[str, list[str]],
    locomotion_profile: str,
    sink: ProgressSink,
    provider: TokenProvider,
    count: int = CANDIDATE_COUNT,
) -> list[Path]:
    """Generate ``count`` design candidates and write them to ``candidates_dir``.

    Returns the list of written PNG paths in order.
    """
    candidates_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for i in range(count):
        sink.emit("progress", {"step": f"candidate_{i+1}_of_{count}"})
        prompt = _build_candidate_prompt(
            style_sentence=style_sentence,
            token_palette=token_palette,
            locomotion_profile=locomotion_profile,
            index=i,
        )
        img: Image.Image = provider.generate_candidate(
            canvas=(canvas_w, canvas_h),
            prompt=prompt,
        )
        img = remove_background(img)
        if img.size != (canvas_w, canvas_h):
            img = img.resize((canvas_w, canvas_h), Image.LANCZOS)

        path = candidates_dir / f"candidate_{i}.png"
        img.save(str(path), format="PNG")
        written.append(path)
        sink.emit("candidate_ready", {"index": i, "path": str(path)})

    sink.emit("done", {"candidates": [str(p) for p in written]})
    return written


# ── prompt helpers ────────────────────────────────────────────────────────────

_LOCOMOTION_HINTS = {
    "walk": "bipedal character, naturally proportioned legs and arms, side view",
    "float": "floating character, no visible legs needed, ethereal or magical feel",
    "fly": "winged or hovering character, wings or hover mechanism visible",
}

_POSE_VARIANTS = [
    "standing idle pose, front-facing three-quarter view",
    "standing idle pose, pure side view",
    "standing idle pose, slight dynamic lean",
]


def _build_candidate_prompt(
    *,
    style_sentence: str,
    token_palette: dict[str, list[str]],
    locomotion_profile: str,
    index: int,
) -> str:
    locomotion_hint = _LOCOMOTION_HINTS.get(locomotion_profile, "")
    pose_variant = _POSE_VARIANTS[index % len(_POSE_VARIANTS)]

    body_colors = token_palette.get("body_neutral", [])[:3]
    accent_colors = token_palette.get("accent_primary", [])[:2]
    highlight_colors = token_palette.get("highlight_neutral", [])[:2]

    color_cue = ""
    if body_colors:
        color_cue += f" Body palette: {', '.join(body_colors)}."
    if accent_colors:
        color_cue += f" Trim/accent: {', '.join(accent_colors)}."
    if highlight_colors:
        color_cue += f" Highlights: {', '.join(highlight_colors)}."

    return (
        f"{style_sentence}. {locomotion_hint}. {pose_variant}."
        f"{color_cue}"
        " Pixel art style with black outline, flat cel-shaded colours."
        " Transparent background. No text, no UI elements."
        " Consistent readable silhouette at small size."
    )

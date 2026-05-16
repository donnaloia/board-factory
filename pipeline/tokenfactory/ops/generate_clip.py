"""Generate Clip operation.

Produces all frames for one animation clip using the key-pose + inter-frame
fill strategy:

1. Generate key poses (contact, passing, …) via ``provider.generate_key_pose``.
   Each key pose is an img2img call with the canonical reference as source.

2. For each inter-frame gap between adjacent key poses, blend the two
   bracketing key frames with ``PIL.Image.blend(alpha=0.5)`` then call
   ``provider.generate_interframe`` on the blend (high structure lock).
   For the loop-closure gap (last key → first frame) the same approach is used
   so the sequence is seamless.

3. Register every frame to the fixed token canvas.

4. Quantize each frame to the token palette.

5. Run loop QA (``steps.loop_qa``).  ``LoopQAFailed`` is caught and logged to
   the sink as a warning rather than aborting the job — the frames are still
   written so the user can inspect and re-run if desired.

Returns the ordered list of written frame ``Path`` objects.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from ..providers.base import TokenProvider
from ..steps.anchor import anchor_character_in_canvas
from ..steps.bg_remove import remove_background
from ..steps.canvas import (
    alpha_bbox_height,
    normalize_character_scale_to_reference,
    register_to_canvas,
)
from ..steps.loop_qa import LoopQAFailed, check_loop
from ..steps.palette_quantize import quantize_to_token_palette
from .progress import ProgressSink


def generate_clip(
    *,
    clip_name: str,
    canonical_img: Image.Image,
    keys_dir: Path,
    frames_dir: Path,
    frame_count: int,
    key_frame_indices: list[int],
    canvas_w: int,
    canvas_h: int,
    style_sentence: str,
    token_palette: dict[str, list[str]],
    locomotion_profile: str,
    provider: TokenProvider,
    sink: ProgressSink,
    loop_qa_threshold: float = 0.07,
) -> list[Path]:
    """Generate all frames for ``clip_name`` and write to ``frames_dir``.

    Returns paths in frame-index order.
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    canvas = (canvas_w, canvas_h)
    ref_h = alpha_bbox_height(canonical_img)

    # ── 1. Key poses ──────────────────────────────────────────────────────────
    key_imgs: dict[int, Image.Image] = {}
    for idx in key_frame_indices:
        sink.emit("progress", {"step": f"{clip_name}_key_{idx}"})
        prompt = _key_pose_prompt(
            clip_name=clip_name,
            frame_idx=idx,
            frame_count=frame_count,
            style_sentence=style_sentence,
            token_palette=token_palette,
            locomotion_profile=locomotion_profile,
        )
        img = provider.generate_key_pose(
            canvas=canvas,
            reference_img=canonical_img,
            prompt=prompt,
        )
        img = remove_background(img)
        img = normalize_character_scale_to_reference(img, ref_h)
        img = register_to_canvas(img, canvas_w, canvas_h)
        img = anchor_character_in_canvas(img, canvas_w, canvas_h)
        key_imgs[idx] = img
        img.save(str(keys_dir / f"frame_{idx}.png"), format="PNG")

    # ── 2. Inter-frames ───────────────────────────────────────────────────────
    all_frames: dict[int, Image.Image] = dict(key_imgs)
    sorted_keys = sorted(key_frame_indices)

    for i in range(frame_count):
        if i in all_frames:
            continue

        prev_key, next_key = _bracket_keys(i, sorted_keys, frame_count)
        alpha = _blend_alpha(i, prev_key, next_key, frame_count)

        key_a = key_imgs[prev_key]
        key_b = key_imgs[next_key]
        blended = Image.blend(
            key_a.convert("RGBA"),
            key_b.convert("RGBA"),
            alpha,
        )
        sink.emit("progress", {"step": f"{clip_name}_interframe_{i}"})
        prompt = _interframe_prompt(
            clip_name=clip_name,
            style_sentence=style_sentence,
            token_palette=token_palette,
        )
        img = provider.generate_interframe(
            canvas=canvas,
            source_img=blended,
            prompt=prompt,
        )
        img = remove_background(img)
        img = normalize_character_scale_to_reference(img, ref_h)
        img = register_to_canvas(img, canvas_w, canvas_h)
        img = anchor_character_in_canvas(img, canvas_w, canvas_h)
        all_frames[i] = img

    # ── 3. Quantize + write ───────────────────────────────────────────────────
    ordered: list[Image.Image] = [all_frames[i] for i in range(frame_count)]
    if token_palette:
        ordered = [quantize_to_token_palette(f, token_palette) for f in ordered]

    written: list[Path] = []
    for i, frame in enumerate(ordered):
        p = frames_dir / f"frame_{i}.png"
        frame.save(str(p), format="PNG")
        written.append(p)

    # ── 4. Loop QA ────────────────────────────────────────────────────────────
    try:
        delta = check_loop(ordered, threshold=loop_qa_threshold)
        sink.emit("loop_qa_pass", {"clip": clip_name, "delta": round(delta, 4)})
    except LoopQAFailed as exc:
        sink.emit(
            "loop_qa_warn",
            {"clip": clip_name, "delta": round(exc.delta, 4), "threshold": loop_qa_threshold},
        )

    sink.emit("clip_done", {"clip": clip_name, "frames": len(written)})
    return written


# ── helpers ──────────────────────────────────────────────────────────────────

def _bracket_keys(
    i: int,
    sorted_keys: list[int],
    frame_count: int,
) -> tuple[int, int]:
    """Find the previous and next key frame indices around ``i`` (with wrap)."""
    prev_key = max((k for k in sorted_keys if k < i), default=None)
    next_key = min((k for k in sorted_keys if k > i), default=None)

    if prev_key is None:
        # i is before first key — wrap: previous is last key in cycle
        prev_key = sorted_keys[-1]
    if next_key is None:
        # i is after last key — wrap: next is first key in next cycle
        next_key = sorted_keys[0]

    return prev_key, next_key


def _blend_alpha(
    i: int,
    prev_key: int,
    next_key: int,
    frame_count: int,
) -> float:
    """Fractional position of ``i`` between ``prev_key`` and ``next_key``.

    Handles the wrap-around case (prev_key > next_key) correctly.
    """
    if prev_key < next_key:
        span = next_key - prev_key
        return (i - prev_key) / span if span > 0 else 0.5
    else:
        # Wrap: distance measured modulo frame_count
        dist_to_next = (next_key - prev_key) % frame_count
        dist_from_prev = (i - prev_key) % frame_count
        return (dist_from_prev / dist_to_next) if dist_to_next > 0 else 0.5


# ── prompt builders ──────────────────────────────────────────────────────────

_KEY_POSE_TEMPLATES: dict[str, list[str]] = {
    "idle_breath": [
        "Idle pose, neutral resting position. Black outline, flat colours.",
        "Idle pose, gentle exhale: torso very slightly compressed inward. "
        "Feet stay at the same canvas position; no vertical or horizontal shift of the whole sprite.",
    ],
    "idle_float": [
        "Floating idle, body at rest, neutral position. Transparent background, pixel art.",
        "Floating idle: subtle internal pose variation only (wings or clothing shift slightly). "
        "Character occupies the exact same region of the frame as frame 1; "
        "no vertical or horizontal translation of the whole sprite.",
    ],
    "drift_horizontal": [
        "Floating drift, starting position, body centred. Pixel art, transparent background.",
        "Floating drift, mid-drift position, slight forward lean. Same character.",
    ],
    "walk_horizontal": [
        # Frame 0 — right-foot contact
        "Side-view walk cycle, frame 1 of 6: RIGHT foot planted firmly on the ground ahead, "
        "LEFT leg swung back behind the body. Right arm back, left arm forward. "
        "Body slightly lowered. Legs are clearly separated — do NOT show both feet together. "
        "Pixel art side view, same character as reference but actively walking.",
        # Frame 2 — left-foot passing / mid-swing
        "Side-view walk cycle, frame 3 of 6: weight fully on RIGHT planted foot, "
        "LEFT leg lifting and swinging forward, knee raised, foot off the ground. "
        "Body at full upright height. Arms switching sides — left arm coming back, right arm coming forward. "
        "Legs clearly mid-swing — do NOT show a static standing pose.",
        # Frame 4 — left-foot contact (mirror of frame 0)
        "Side-view walk cycle, frame 5 of 6: LEFT foot planted firmly on the ground ahead, "
        "RIGHT leg swung back behind the body. Left arm back, right arm forward. "
        "Body slightly lowered. Legs are clearly separated — exact mirror of the first contact frame.",
    ],
    "fly_horizontal": [
        "Side-view fly cycle, frame 1 of 6: wings at their LOWEST point, fully extended downward. "
        "Body at its highest position. Pixel art side view, same character as reference but actively flying.",
        "Side-view fly cycle, frame 3 of 6: wings rising upward, roughly horizontal. "
        "Body at mid height. Wings are clearly different from frame 1 — do NOT show a static glide pose.",
        "Side-view fly cycle, frame 5 of 6: wings at their HIGHEST point, fully raised. "
        "Body at its lowest position. Exact opposite of the first frame's wing position.",
    ],
    "idle_hover": [
        "Hovering idle, body centred, rotors/wings at rest. Pixel art.",
        "Hovering idle: subtle rotor/wing motion only. "
        "Character body stays in the exact same canvas position as frame 1; no shift.",
    ],
}

_FALLBACK_KEY_TEMPLATES = [
    "Animation frame {idx} of {total}: key pose.",
    "Animation frame {idx} of {total}: alternate key pose.",
]


def _key_pose_prompt(
    *,
    clip_name: str,
    frame_idx: int,
    frame_count: int,
    style_sentence: str,
    token_palette: dict[str, list[str]],
    locomotion_profile: str,
) -> str:
    templates = _KEY_POSE_TEMPLATES.get(clip_name, _FALLBACK_KEY_TEMPLATES)
    # Distribute key-frame indices across the template list
    template = templates[frame_idx % len(templates)]
    pose_desc = template.format(idx=frame_idx + 1, total=frame_count)

    color_cue = _palette_cue(token_palette)
    return (
        f"{style_sentence}. {pose_desc}.{color_cue}"
        " Pixel art, black outline, flat cel-shaded colours."
        " Transparent background. No text. Consistent silhouette."
        " Match character design exactly from reference image."
        " Keep character pixel scale identical across all frames in this clip."
        " Character bottom-centre must be at the same canvas position in every frame."
        " Do not translate the whole sprite up, down, left, or right."
        " This is an ANIMATION FRAME — the pose described above must be clearly different"
        " from a neutral standing pose; do not revert to the reference stance."
    )


def _interframe_prompt(
    *,
    clip_name: str,
    style_sentence: str,
    token_palette: dict[str, list[str]],
) -> str:
    color_cue = _palette_cue(token_palette)
    return (
        f"{style_sentence}. Natural fluid motion continuation.{color_cue}"
        " Same character, same palette, same style."
        " Smooth in-between pose between the two shown frames."
        " Pixel art, black outline, flat colours, transparent background."
        " Do not change overall character size—only the pose between frames."
        " Character must stay at the exact same position in the canvas as the input frames."
        " No whole-sprite translation; only internal pose animation."
    )


def _palette_cue(token_palette: dict[str, list[str]]) -> str:
    body = token_palette.get("body_neutral", [])[:2]
    accent = token_palette.get("accent_primary", [])[:1]
    parts = []
    if body:
        parts.append(f"Body colours: {', '.join(body)}")
    if accent:
        parts.append(f"Trim: {accent[0]}")
    if not parts:
        return ""
    return " " + ". ".join(parts) + "."

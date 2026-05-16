"""Offline I2V provider for development and tests.

Produces deterministic candidates by transforming the source PNG with cheap
per-candidate effects (hue cycle, subpixel drift, brightness pulse) so the
full app pipeline — proposal write, manifest, commit, live promotion — can
be exercised without an external API or API key.

The output is intentionally simple: each frame is a small shifted/tinted
variant of the source so encoding produces real animated GIFs/APNGs that
the browser can preview.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageChops

from .base import Clip


@dataclass(frozen=True)
class MockI2VProvider:
    name: str = "mock"
    model_id: str = "mock-i2v-v0"

    def generate(
        self,
        source_png: bytes,
        *,
        fps: int,
        duration_ms: int,
        candidates: int,
        seed: int | None = None,
        animation_prompt: str = "",
    ) -> list[Clip]:
        if candidates <= 0:
            return []
        source = Image.open(io.BytesIO(source_png)).convert("RGBA")
        frame_count = max(2, int(round(fps * duration_ms / 1000.0)))
        seed_v = int(seed or 0)
        clips: list[Clip] = []
        hint = (animation_prompt or "").strip()
        hint_note = f' · "{hint[:80]}…"' if len(hint) > 80 else (f' · "{hint}"' if hint else "")
        for c in range(candidates):
            frames = _render_candidate(source, frame_count, candidate_index=c, seed=seed_v + c)
            clips.append(
                Clip(
                    frames=frames,
                    fps=fps,
                    seed=seed_v + c,
                    notes=f"mock candidate {c} ({_effect_name(c)}){hint_note}",
                )
            )
        return clips

    def cost_estimate(self, *, candidates: int, duration_ms: int) -> float:
        return 0.0


_EFFECTS = ("hue_cycle", "drift", "pulse")


def _effect_name(candidate_index: int) -> str:
    return _EFFECTS[candidate_index % len(_EFFECTS)]


def _render_candidate(
    source: Image.Image,
    frame_count: int,
    *,
    candidate_index: int,
    seed: int,
) -> list[Image.Image]:
    """Render one candidate's frames using a deterministic per-candidate effect."""
    effect = _effect_name(candidate_index)
    if effect == "hue_cycle":
        return _hue_cycle_frames(source, frame_count)
    if effect == "drift":
        return _drift_frames(source, frame_count, seed=seed)
    return _pulse_frames(source, frame_count)


def _hue_cycle_frames(source: Image.Image, frame_count: int) -> list[Image.Image]:
    base_hsv = source.convert("HSV")
    h, s, v = base_hsv.split()
    out: list[Image.Image] = []
    for i in range(frame_count):
        delta = int(round(20.0 * math.sin(2.0 * math.pi * i / frame_count)))
        shifted_h = h.point(lambda px, d=delta: (px + d) % 256)
        merged = Image.merge("HSV", (shifted_h, s, v)).convert("RGBA")
        merged.putalpha(source.split()[-1])
        out.append(merged)
    return out


def _drift_frames(source: Image.Image, frame_count: int, *, seed: int) -> list[Image.Image]:
    out: list[Image.Image] = []
    for i in range(frame_count):
        angle = 2.0 * math.pi * i / frame_count + (seed % 7) * 0.3
        dx = int(round(math.cos(angle)))
        dy = int(round(math.sin(angle)))
        out.append(ImageChops.offset(source, dx, dy))
    return out


def _pulse_frames(source: Image.Image, frame_count: int) -> list[Image.Image]:
    out: list[Image.Image] = []
    for i in range(frame_count):
        factor = 1.0 + 0.08 * math.sin(2.0 * math.pi * i / frame_count)
        out.append(_apply_brightness(source, factor))
    return out


def _apply_brightness(img: Image.Image, factor: float) -> Image.Image:
    rgb = img.convert("RGB")
    scaled = rgb.point(lambda px, f=factor: max(0, min(255, int(px * f))))
    out = scaled.convert("RGBA")
    out.putalpha(img.split()[-1])
    return out

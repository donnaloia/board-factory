"""Provider protocol for image-to-video generation.

A provider receives the source PNG plus target loop parameters and returns
N independent candidate clips. It does not encode to GIF/APNG — that happens
in :mod:`space_animations.steps.encode` so all providers share one encoder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class Clip:
    """Raw frames produced by an I2V provider for one candidate.

    ``frames`` is the full list of PIL ``Image`` objects in playback order at
    ``fps`` frames per second. Frame count = ``round(fps * duration_s)``;
    providers SHOULD honor the requested fps/duration but small drift is
    acceptable (see spec §G5 manifest fields).
    """

    frames: list[Image.Image]
    fps: int
    seed: int | None = None
    notes: str = ""


class I2VProvider(Protocol):
    name: str
    model_id: str

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
        ...

    def cost_estimate(self, *, candidates: int, duration_ms: int) -> float:
        ...

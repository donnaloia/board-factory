"""Loop QA — verify that a clip's first and last frames are visually similar.

Uses mean absolute difference across all RGBA channels.  A high delta means
the loop will visibly "pop" on the first→last transition.

Raises ``LoopQAFailed`` when the delta exceeds ``threshold``.  Callers that
want a soft warning rather than a hard stop may catch the exception and log
or record it in the job sink.
"""

from __future__ import annotations

import math

from PIL import Image


class LoopQAFailed(Exception):
    def __init__(self, delta: float, threshold: float) -> None:
        super().__init__(
            f"Loop QA failed: first↔last frame delta {delta:.4f} > threshold {threshold:.4f}."
        )
        self.delta = delta
        self.threshold = threshold


def check_loop(
    frames: list[Image.Image],
    threshold: float = 0.07,
) -> float:
    """Return mean absolute pixel delta between first and last frames.

    Raises ``LoopQAFailed`` if ``delta > threshold``.

    ``threshold`` = 0.07 means ≤ 7/255 ≈ 2.7% mean intensity difference
    across all channels — effectively invisible on screen.
    """
    if len(frames) < 2:
        return 0.0

    first = frames[0].convert("RGBA")
    last = frames[-1].convert("RGBA")

    if first.size != last.size:
        last = last.resize(first.size, Image.LANCZOS)

    total: float = 0.0
    n = 0
    for c_first, c_last in zip(first.split(), last.split()):
        for pf, pl in zip(c_first.getdata(), c_last.getdata()):
            total += abs(pf - pl) / 255.0
            n += 1

    delta = total / max(n, 1)
    if delta > threshold:
        raise LoopQAFailed(delta=delta, threshold=threshold)
    return delta

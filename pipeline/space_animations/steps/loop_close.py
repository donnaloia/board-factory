"""Loop-closure strategies.

Per spec §6.1: target a seamless loop when the provider supports it; fall
back to a soft seam (crossfade / pingpong / dissolve) so the clip still
plays cleanly when triggered repeatedly in an engine.

Pure functions over PIL ``Image`` lists. No I/O.
"""

from __future__ import annotations

from PIL import Image

from ..config import ALLOWED_LOOP_STRATEGIES


def close_loop(frames: list[Image.Image], strategy: str) -> list[Image.Image]:
    """Apply ``strategy`` to ``frames`` and return the new (possibly longer) list.

    Raises ``ValueError`` for unknown strategies — pipeline callers should
    validate against ``config.ALLOWED_LOOP_STRATEGIES`` before reaching here.
    """
    if strategy not in ALLOWED_LOOP_STRATEGIES:
        raise ValueError(
            f"Unknown loop strategy {strategy!r}. "
            f"Expected one of {ALLOWED_LOOP_STRATEGIES}."
        )
    if not frames:
        return frames
    if strategy == "seamless":
        return list(frames)
    if strategy == "crossfade":
        return _crossfade_tail_to_head(frames)
    if strategy == "pingpong":
        return _pingpong(frames)
    if strategy == "dissolve":
        return _dissolve_to_first(frames)
    return list(frames)


def _crossfade_tail_to_head(frames: list[Image.Image]) -> list[Image.Image]:
    """Replace the last ``k`` frames with a smooth blend toward ``frames[0]``.

    ``k`` defaults to one quarter of the clip (min 2) so a 90-frame loop gets
    ~22 blended frames at the seam.
    """
    n = len(frames)
    if n < 4:
        return list(frames)
    k = max(2, n // 4)
    head = frames[:n - k]
    tail = frames[n - k:]
    target = frames[0].convert("RGBA")
    blended: list[Image.Image] = []
    for i, f in enumerate(tail):
        alpha = (i + 1) / (k + 1)
        blended.append(Image.blend(f.convert("RGBA"), target, alpha))
    return head + blended


def _pingpong(frames: list[Image.Image]) -> list[Image.Image]:
    """Append the reverse of the interior frames so playback ends where it started."""
    if len(frames) < 3:
        return list(frames)
    return list(frames) + list(reversed(frames[1:-1]))


def _dissolve_to_first(frames: list[Image.Image]) -> list[Image.Image]:
    """Crossfade the entire tail directly into the first frame.

    Wider blend than ``crossfade``; trades motion for a softer seam.
    """
    n = len(frames)
    if n < 2:
        return list(frames)
    target = frames[0].convert("RGBA")
    out: list[Image.Image] = [frames[0]]
    for i in range(1, n):
        alpha = i / (n - 1) * 0.5
        out.append(Image.blend(frames[i].convert("RGBA"), target, alpha))
    return out

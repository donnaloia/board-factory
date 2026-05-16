"""Encode a list of PIL frames as an animated GIF or APNG.

GIF gives the broadest browser support; APNG preserves alpha at the cost of
larger files. Both are produced by Pillow's ``save_all`` path. We deliberately
keep this module byte-shaped (returns ``bytes``) so the caller decides
where to write — the pipeline never owns workspace paths.
"""

from __future__ import annotations

import io

from PIL import Image

from ..config import ALLOWED_ENCODINGS


def file_extension_for(encoding: str) -> str:
    """Return the canonical file extension for ``encoding`` (without the dot)."""
    e = encoding.strip().lower()
    if e == "apng":
        return "apng"
    return "gif"


def encode_clip(frames: list[Image.Image], *, fps: int, encoding: str) -> bytes:
    """Encode ``frames`` at ``fps`` as either GIF or APNG. Returns the file bytes.

    Raises ``ValueError`` for unknown encodings or empty frame lists so a bad
    spec fails fast rather than producing a 0-byte file on disk.
    """
    if not frames:
        raise ValueError("encode_clip requires at least one frame")
    enc = encoding.strip().lower()
    if enc not in ALLOWED_ENCODINGS:
        raise ValueError(
            f"Unknown encoding {encoding!r}. Expected one of {ALLOWED_ENCODINGS}."
        )
    if fps <= 0:
        raise ValueError(f"fps must be positive (got {fps})")
    duration_ms = max(1, int(round(1000.0 / fps)))
    if enc == "gif":
        return _encode_gif(frames, duration_ms=duration_ms)
    return _encode_apng(frames, duration_ms=duration_ms)


def _encode_gif(frames: list[Image.Image], *, duration_ms: int) -> bytes:
    paletted = [f.convert("P", palette=Image.Palette.ADAPTIVE) for f in frames]
    buf = io.BytesIO()
    paletted[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=paletted[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    return buf.getvalue()


def _encode_apng(frames: list[Image.Image], *, duration_ms: int) -> bytes:
    rgba = [f.convert("RGBA") for f in frames]
    buf = io.BytesIO()
    rgba[0].save(
        buf,
        format="PNG",
        save_all=True,
        append_images=rgba[1:],
        duration=duration_ms,
        loop=0,
        disposal=1,
    )
    return buf.getvalue()

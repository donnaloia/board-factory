"""Background removal for token sprites.

``gpt-image-2`` always returns opaque images — even when prompted for a
transparent background — because it does not support the ``background:
transparent`` API parameter.  This step runs the U2Net segmentation model via
``rembg`` to strip the solid background and return a proper RGBA image with
alpha=0 outside the character silhouette.

The ONNX session is created once and cached for the lifetime of the process;
subsequent calls within the same worker are essentially free of model-load
overhead (only inference time, ~0.3–0.8 s per frame on CPU).

If ``rembg`` or ``onnxruntime`` is not installed the function degrades
gracefully: it logs a warning and returns the image converted to RGBA with the
background intact.  This keeps tests and non-OpenAI providers working without
the optional dependency.
"""

from __future__ import annotations

import functools
import logging

from PIL import Image

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _session():
    """Lazily load and cache the U2Net ONNX session."""
    from rembg import new_session  # type: ignore[import-untyped]
    return new_session("u2net")


def remove_background(img: Image.Image) -> Image.Image:
    """Return an RGBA copy of ``img`` with the background made transparent.

    Uses the U2Net model via ``rembg``.  Falls back to a plain RGBA conversion
    (background intact) if the optional dependency is unavailable.
    """
    try:
        from rembg import remove  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "rembg is not installed — background will not be removed. "
            "Install with: pip install 'rembg[cpu]'"
        )
        return img.convert("RGBA")

    return remove(img.convert("RGBA"), session=_session())

"""PixelLab provider — hosted pixel-art generation API.

PixelLab (https://www.pixellab.ai) offers three relevant endpoints:
- /v1/generate-image-pixflux: text-to-image at native pixel-art resolution
- /v1/generate-image-bitforge: image-to-image with style/composition control
- /v1/inpaint-image: masked-region regeneration

This provider wraps those endpoints behind the PixelArtProvider interface.

Note: API endpoint paths and request bodies are written against PixelLab's
public docs as of writing. If their API changes, update the URLs and request
shapes in `_post_pixellab` and the per-method body builders below.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any

import httpx
from PIL import Image

from ..base import PixelArtProvider


_BASE_URL = "https://api.pixellab.ai/v1"
_TIMEOUT_SEC = 120

# Approximate USD cost per image at 128x128 (typical board factory size).
# Update against your actual PixelLab plan billing as needed.
_COST_PER_IMAGE = 0.03

# Named user-facing model presets. Each maps to PixelLab's per-call style knobs
# (detail / shading / outline). Pixflux is the txt2img endpoint; img2img always
# routes through bitforge regardless of the preset.
PIXELLAB_PRESETS: dict[str, dict[str, str]] = {
    "pixflux_sharp": {
        "label": "Pixflux Sharp",
        "description": "High detail, basic shading, single black outline.",
        "detail": "highly detailed",
        "shading": "basic shading",
        "outline": "single color black outline",
    },
    "pixflux_soft": {
        "label": "Pixflux Soft",
        "description": "Medium detail, basic shading, no outline.",
        "detail": "medium detail",
        "shading": "basic shading",
        "outline": "lineless",
    },
    "pixflux_bold": {
        "label": "Pixflux Bold",
        "description": "High detail, flat shading, bold black outline.",
        "detail": "highly detailed",
        "shading": "flat shading",
        "outline": "single color black outline",
    },
}
_DEFAULT_PRESET = "pixflux_sharp"


def list_pixellab_presets() -> list[dict[str, str]]:
    """Return UI-friendly preset descriptors (id, label, description)."""
    return [
        {"id": pid, "label": p["label"], "description": p["description"]}
        for pid, p in PIXELLAB_PRESETS.items()
    ]


class PixelLabProvider(PixelArtProvider):
    @property
    def name(self) -> str:
        return "pixellab"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        preset: str | None = None,
    ) -> None:
        # Prefer the explicit ``api_key`` arg; fall back to the env var so
        # CLI / legacy callers that don't pass-through still work.
        self._api_key = (api_key or os.environ.get("PIXELLAB_API_KEY", "")).strip()
        if not self._api_key:
            raise RuntimeError(
                "PIXELLAB_API_KEY is not set. Add it under the board-factory "
                "service in docker-compose.yml, or set BOARDFACTORY_PROVIDER: mock "
                "to test the pipeline without an API key."
            )
        self._preset = (preset or _DEFAULT_PRESET).strip()
        if self._preset not in PIXELLAB_PRESETS:
            self._preset = _DEFAULT_PRESET
        self._params = PIXELLAB_PRESETS[self._preset]

    # ────────────────── public API ──────────────────

    def generate(
        self,
        prompt: str,
        size: tuple[int, int],
        n: int = 1,
        style_reference: bytes | None = None,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        body: dict[str, Any] = {
            "description": prompt,
            "image_size": {"width": size[0], "height": size[1]},
            "no_background": True,
            "outline": self._params["outline"],
            "shading": self._params["shading"],
            "detail": self._params["detail"],
        }
        if palette:
            body["forced_palette"] = [list(c) for c in palette]
        if style_reference:
            body["style_image"] = {"type": "base64", "base64": _encode(style_reference)}

        return [self._post("generate-image-pixflux", body) for _ in range(n)]

    def img2img(
        self,
        prompt: str,
        source_image: bytes,
        size: tuple[int, int],
        strength: float = 0.75,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        body: dict[str, Any] = {
            "description": prompt,
            "image_size": {"width": size[0], "height": size[1]},
            "init_image": {"type": "base64", "base64": _encode(source_image)},
            "init_image_strength": strength,
            "no_background": True,
        }
        if palette:
            body["forced_palette"] = [list(c) for c in palette]

        return [self._post("generate-image-bitforge", body) for _ in range(n)]

    def inpaint(
        self,
        prompt: str,
        source_image: bytes,
        mask_image: bytes,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        body: dict[str, Any] = {
            "description": prompt,
            "image": {"type": "base64", "base64": _encode(source_image)},
            "mask": {"type": "base64", "base64": _encode(mask_image)},
        }
        if palette:
            body["forced_palette"] = [list(c) for c in palette]

        return [self._post("inpaint-image", body) for _ in range(n)]

    def cost_estimate(self, size: tuple[int, int], n: int) -> float:
        # PixelLab pricing scales mildly with output size; ~$0.03 covers typical
        # board factory sizes (32x32 → 256x256). For very large outputs, scale up.
        scale = max(1.0, (size[0] * size[1]) / (128 * 128))
        return _COST_PER_IMAGE * scale * n

    # ────────────────── HTTP plumbing ──────────────────

    def _post(self, endpoint: str, body: dict[str, Any]) -> bytes:
        url = f"{_BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=_TIMEOUT_SEC) as client:
            r = client.post(url, json=body, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(
                    f"PixelLab {endpoint} returned {r.status_code}: {r.text[:200]}"
                )
            data = r.json()
        # PixelLab responses wrap the image as base64 under `image.base64`.
        b64 = data.get("image", {}).get("base64") or data.get("base64")
        if not b64:
            raise RuntimeError(f"PixelLab {endpoint} response missing image data: {data}")
        return base64.b64decode(b64)


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def png_bytes(img: Image.Image) -> bytes:
    """Helper for callers: convert a PIL image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

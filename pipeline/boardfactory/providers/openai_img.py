"""OpenAI image provider — gpt-image-1 / DALL-E backed generation.

Uses the OpenAI Images API for all three draw modes:

  generate  → POST /v1/images/generations  (gpt-image-1)
  img2img   → POST /v1/images/edits        (gpt-image-1 with source image)
  inpaint   → POST /v1/images/edits        (gpt-image-1 with source + mask)

OpenAI only supports fixed canvas sizes (smallest: 1024×1024), so every
call generates at 1024×1024 and is then resized to the requested board-tile
size with LANCZOS before being handed back to draw_cell for cleanup.

Cost reference (gpt-image-1, medium quality, 1024×1024 as of 2025):
  ~$0.04 per image. Use quality="low" to halve that during testing.
"""

from __future__ import annotations

import base64
import io
import os

import httpx
from PIL import Image

from .base import PixelArtProvider


_BASE_URL = "https://api.openai.com/v1"
_GEN_SIZE  = "1024x1024"       # smallest gpt-image-1 supports
_QUALITY   = "low"             # low | medium | high — use low for cheap tests
_COST_LOW  = 0.011             # gpt-image-1 low-quality 1024×1024 per image
_COST_MED  = 0.042
_COST_HIGH = 0.167

_COST_MAP = {"low": _COST_LOW, "medium": _COST_MED, "high": _COST_HIGH}

# Prepended to every prompt to steer gpt-image-1 toward pixel-art style.
_STYLE_PREFIX = (
    "pixel art style, board game tile, flat colors, crisp edges, "
    "no gradients, limited palette. "
)


class OpenAIImageProvider(PixelArtProvider):
    """Wraps gpt-image-1 behind the PixelArtProvider interface."""

    @property
    def name(self) -> str:
        return "openai"

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Save it in Account → Connections → "
                "OpenAI / ChatGPT, or set OPENAI_API_KEY in docker-compose.yml."
            )

    # ────────────────────────── public API ──────────────────────────

    def generate(
        self,
        prompt: str,
        size: tuple[int, int],
        n: int = 1,
        style_reference: bytes | None = None,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        full_prompt = _STYLE_PREFIX + prompt if prompt else _STYLE_PREFIX.rstrip(". ,")
        resp = self._json_post(
            f"{_BASE_URL}/images/generations",
            {
                "model": "gpt-image-1",
                "prompt": full_prompt,
                "n": min(n, 4),
                "size": _GEN_SIZE,
                "quality": _QUALITY,
            },
        )
        return [self._to_target_size(raw, size) for raw in self._decode(resp)]

    def img2img(
        self,
        prompt: str,
        source_image: bytes,
        size: tuple[int, int],
        strength: float = 0.75,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        full_prompt = _STYLE_PREFIX + prompt if prompt else _STYLE_PREFIX.rstrip(". ,")
        src_buf = self._to_api_size(source_image)
        resp = self._multipart_post(
            f"{_BASE_URL}/images/edits",
            data={
                "model": "gpt-image-1",
                "prompt": full_prompt,
                "n": str(min(n, 4)),
                "size": _GEN_SIZE,
                "quality": _QUALITY,
            },
            files={"image": ("source.png", src_buf, "image/png")},
        )
        return [self._to_target_size(raw, size) for raw in self._decode(resp)]

    def inpaint(
        self,
        prompt: str,
        source_image: bytes,
        mask_image: bytes,
        n: int = 1,
        palette: list[tuple[int, int, int]] | None = None,
    ) -> list[bytes]:
        # Inpaint target size comes from source image dimensions.
        src_img = Image.open(io.BytesIO(source_image)).convert("RGBA")
        target_size = src_img.size

        full_prompt = _STYLE_PREFIX + prompt if prompt else _STYLE_PREFIX.rstrip(". ,")
        src_buf  = self._to_api_size(source_image)
        mask_buf = self._mask_to_api_size(mask_image)

        resp = self._multipart_post(
            f"{_BASE_URL}/images/edits",
            data={
                "model": "gpt-image-1",
                "prompt": full_prompt,
                "n": str(min(n, 4)),
                "size": _GEN_SIZE,
                "quality": _QUALITY,
            },
            files={
                "image": ("source.png", src_buf,  "image/png"),
                "mask":  ("mask.png",   mask_buf, "image/png"),
            },
        )
        return [self._to_target_size(raw, target_size) for raw in self._decode(resp)]

    def cost_estimate(self, size: tuple[int, int], n: int) -> float:
        return _COST_MAP.get(_QUALITY, _COST_LOW) * n

    # ────────────────────────── helpers ──────────────────────────

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _json_post(self, url: str, body: dict) -> dict:
        r = httpx.post(
            url,
            json=body,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            timeout=120.0,
        )
        self._raise(r)
        return r.json()

    def _multipart_post(self, url: str, data: dict, files: dict) -> dict:
        r = httpx.post(
            url,
            data=data,
            files=files,
            headers=self._auth_headers(),
            timeout=120.0,
        )
        self._raise(r)
        return r.json()

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if not r.is_success:
            body = ""
            try:
                body = r.json().get("error", {}).get("message", "")
            except Exception:
                body = r.text[:200]
            raise RuntimeError(f"OpenAI API {r.status_code}: {body}")

    @staticmethod
    def _decode(resp: dict) -> list[bytes]:
        """Extract PNG bytes from a generations/edits response (b64 or URL)."""
        out: list[bytes] = []
        for item in resp.get("data", []):
            b64 = item.get("b64_json")
            if b64:
                out.append(base64.b64decode(b64))
                continue
            url = item.get("url")
            if url:
                r = httpx.get(url, timeout=30.0)
                r.raise_for_status()
                out.append(r.content)
        return out

    @staticmethod
    def _to_api_size(png_bytes: bytes) -> io.BytesIO:
        """Resize source image to 1024×1024 for the edits endpoint."""
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        img = img.resize((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    @staticmethod
    def _mask_to_api_size(mask_bytes: bytes) -> io.BytesIO:
        """Resize + invert mask: white = regenerate (OpenAI convention)."""
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
        mask = mask.resize((1024, 1024), Image.NEAREST)
        # OpenAI mask: transparent (alpha=0) = regenerate; opaque = preserve.
        # Convert greyscale mask (white=regen) to RGBA with alpha channel.
        rgba = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        # White pixels in the greyscale mask → fully transparent in RGBA mask
        # (so OpenAI regenerates those areas).
        for x in range(1024):
            for y in range(1024):
                v = mask.getpixel((x, y))
                if v > 128:          # regen area
                    rgba.putpixel((x, y), (0, 0, 0, 0))    # transparent
                else:                # preserve area
                    rgba.putpixel((x, y), (0, 0, 0, 255))  # opaque black
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        buf.seek(0)
        return buf

    @staticmethod
    def _to_target_size(png_bytes: bytes, size: tuple[int, int]) -> bytes:
        """Downscale from 1024×1024 to the board tile's actual pixel size."""
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        if img.size != size:
            img = img.resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

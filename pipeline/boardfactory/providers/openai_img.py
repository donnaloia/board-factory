"""OpenAI image provider — gpt-image-2 (Images API).

Uses the OpenAI Images API for all three draw modes:

  generate  → POST /v1/images/generations
  img2img   → POST /v1/images/edits       (with source image)
  inpaint   → POST /v1/images/edits       (with source + mask)

OpenAI exposes a small set of fixed ``size`` strings (see API docs). **Text-to-image**
(``generate``) picks the candidate whose **aspect ratio** is closest to the
requested tile ``(width, height)`` — e.g. portrait tiles use ``1024x1536`` instead
of always ``1024x1024`` — then ``_to_target_size`` scales to the exact pixel size.
**Edits** (``img2img`` / ``inpaint``) still use the previous behaviour until a later
pass aligns those endpoints the same way.

See https://platform.openai.com/pricing for current per-image pricing;
`_QUALITY` controls low / medium / high.
"""

from __future__ import annotations

import base64
import io
import os
import time

import httpx
from PIL import Image

from .base import PixelArtProvider

# Retry config for 429 / 5xx transient errors.
_MAX_RETRIES = 5
_RETRY_BASE_S = 5.0   # first wait: 5 s
_RETRY_MAX_S  = 60.0  # cap each wait at 60 s


_BASE_URL = "https://api.openai.com/v1"
_GEN_SIZE = "1024x1024"       # default / square; see ``_GENERATION_SIZE_CHOICES``

# GPT Image models accept a fixed set of ``size`` values. We choose the candidate
# whose width/height ratio best matches the board tile to avoid heavy anamorphic
# stretch when mapping API output → ``spec.size`` (Phase 1: ``generate`` only).
# Ref: https://platform.openai.com/docs/api-reference/images/create
_GENERATION_SIZE_CHOICES: tuple[tuple[str, int, int], ...] = (
    ("1024x1024", 1024, 1024),
    ("1024x1536", 1024, 1536),
    ("1536x1024", 1536, 1024),
)


def _generation_size_for_target(target: tuple[int, int]) -> str:
    """Return OpenAI ``images/generations`` ``size`` closest to target aspect ratio."""
    tw, th = target
    if tw <= 0 or th <= 0:
        return _GEN_SIZE
    target_ar = tw / th
    best_label = _GEN_SIZE
    best_diff = float("inf")
    for label, aw, ah in _GENERATION_SIZE_CHOICES:
        api_ar = aw / ah
        diff = abs(api_ar - target_ar)
        if diff < best_diff:
            best_diff = diff
            best_label = label
    return best_label
_DEFAULT_QUALITY = "low"      # low | medium | high
_DEFAULT_MODEL = "gpt-image-2"
# Fallback estimates for ui cost hints — verify against OpenAI pricing.
_COST_LOW = 0.011
_COST_MED = 0.042
_COST_HIGH = 0.167

_COST_MAP = {"low": _COST_LOW, "medium": _COST_MED, "high": _COST_HIGH}
_VALID_MODELS = {"gpt-image-1", "gpt-image-2"}
_VALID_QUALITIES = set(_COST_MAP.keys())

# Prepended to every prompt — pixel discipline without implying a monochrome look.
_STYLE_PREFIX = (
    "pixel art board game tile, flat fills, crisp pixel edges, no smooth gradients; "
    "rich cohesive palette with varied accents (warm metals, jewel tones, bone, "
    "cool shadows) — avoid collapsing to one hue across the tile. "
)


# OpenAI Images API allows at most 4 images per HTTP request for generations/edits.
_MAX_IMAGES_PER_REQUEST = 4


class OpenAIImageProvider(PixelArtProvider):
    """Wraps GPT Image models (gpt-image-2) behind the PixelArtProvider interface."""

    @property
    def name(self) -> str:
        return "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        quality: str | None = None,
    ) -> None:
        # Prefer the explicit ``api_key`` arg; fall back to the env var so
        # callers that haven't been migrated to pass-through yet keep working.
        self._api_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Save it in Account → Connections → "
                "OpenAI / ChatGPT, or set OPENAI_API_KEY in docker-compose.yml."
            )
        chosen_model = (model or _DEFAULT_MODEL).strip()
        chosen_quality = (quality or _DEFAULT_QUALITY).strip()
        self._model = chosen_model if chosen_model in _VALID_MODELS else _DEFAULT_MODEL
        self._quality = chosen_quality if chosen_quality in _VALID_QUALITIES else _DEFAULT_QUALITY

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
        out: list[bytes] = []
        api_size = _generation_size_for_target(size)
        while len(out) < n:
            batch = min(n - len(out), _MAX_IMAGES_PER_REQUEST)
            resp = self._json_post(
                f"{_BASE_URL}/images/generations",
                {
                    "model": self._model,
                    "prompt": full_prompt,
                    "n": batch,
                    "size": api_size,
                    "quality": self._quality,
                },
            )
            chunk = [self._to_target_size(raw, size) for raw in self._decode(resp)]
            if not chunk:
                break
            out.extend(chunk)
        return out[:n]

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
        out: list[bytes] = []
        while len(out) < n:
            batch = min(n - len(out), _MAX_IMAGES_PER_REQUEST)
            src_buf = self._to_api_size(source_image)
            resp = self._multipart_post(
                f"{_BASE_URL}/images/edits",
                data={
                    "model": self._model,
                    "prompt": full_prompt,
                    "n": str(batch),
                    "size": _GEN_SIZE,
                    "quality": self._quality,
                },
                files={"image": ("source.png", src_buf, "image/png")},
            )
            chunk = [self._to_target_size(raw, size) for raw in self._decode(resp)]
            if not chunk:
                break
            out.extend(chunk)
        return out[:n]

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
        out: list[bytes] = []
        while len(out) < n:
            batch = min(n - len(out), _MAX_IMAGES_PER_REQUEST)
            src_buf = self._to_api_size(source_image)
            mask_buf = self._mask_to_api_size(mask_image)
            resp = self._multipart_post(
                f"{_BASE_URL}/images/edits",
                data={
                    "model": self._model,
                    "prompt": full_prompt,
                    "n": str(batch),
                    "size": _GEN_SIZE,
                    "quality": self._quality,
                },
                files={
                    "image": ("source.png", src_buf, "image/png"),
                    "mask": ("mask.png", mask_buf, "image/png"),
                },
            )
            chunk = [
                self._to_target_size(raw, target_size) for raw in self._decode(resp)
            ]
            if not chunk:
                break
            out.extend(chunk)
        return out[:n]

    def cost_estimate(self, size: tuple[int, int], n: int) -> float:
        return _COST_MAP.get(self._quality, _COST_LOW) * n

    # ────────────────────────── helpers ──────────────────────────

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _json_post(self, url: str, body: dict) -> dict:
        last_exc: Exception | None = None
        wait = _RETRY_BASE_S
        for attempt in range(_MAX_RETRIES):
            r = httpx.post(
                url,
                json=body,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=120.0,
            )
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(self._error_body(r))
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            self._raise(r)
            return r.json()
        raise RuntimeError(
            f"OpenAI API gave up after {_MAX_RETRIES} attempts: {last_exc}"
        )

    def _multipart_post(self, url: str, data: dict, files: dict) -> dict:
        last_exc: Exception | None = None
        wait = _RETRY_BASE_S
        for attempt in range(_MAX_RETRIES):
            r = httpx.post(
                url,
                data=data,
                files=files,
                headers=self._auth_headers(),
                timeout=120.0,
            )
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(self._error_body(r))
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            self._raise(r)
            return r.json()
        raise RuntimeError(
            f"OpenAI API gave up after {_MAX_RETRIES} attempts: {last_exc}"
        )

    @staticmethod
    def _error_body(r: httpx.Response) -> str:
        try:
            return r.json().get("error", {}).get("message", "") or r.text[:200]
        except Exception:
            return r.text[:200]

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if not r.is_success:
            raise RuntimeError(f"OpenAI API {r.status_code}: {OpenAIImageProvider._error_body(r)}")

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
        """Resize API output (fixed catalog size, e.g. 1024×1536) to ``spec.size``."""
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        if img.size != size:
            img = img.resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

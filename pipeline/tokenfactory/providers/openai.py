"""OpenAI-backed token provider.

Strategy (hybrid — same family as ``space_animations.providers.openai``):

Key poses
    One ``/v1/images/edits`` call per key-pose frame, with the locked
    canonical reference as source.  Prompt = style sentence + palette cue
    + per-frame pose description.

Inter-frames
    The caller passes an ``source_img`` that is already a 50 % ``PIL.blend``
    of the two adjacent key-pose frames.  We run one more ``/images/edits``
    call on that blend with a "hold the structure" prompt so the result is a
    coherent mid-point rather than a pure alpha composite.

Design candidates
    Plain text-to-image via ``/v1/images/generations``.

All images are generated at ``1024×1024`` (gpt-image-2 required size) then
downscaled to the token canvas after retrieval.

HTTP reads default to 300s for generations/edits (slow under load); set
``TOKENFACTORY_HTTP_READ_TIMEOUT_S`` to override. ``ReadTimeout`` is retried like 429/5xx.
"""

from __future__ import annotations

import base64
import io
import os
import time
from dataclasses import dataclass

import httpx
from PIL import Image


_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-image-2"
_API_SIZE = "1024x1024"

_MAX_RETRIES = 5
_RETRY_BASE_S = 5.0
_RETRY_MAX_S = 60.0
_COST_PER_IMAGE_USD = 0.011

#: Image edits/generations often exceed 120s under load; override via env if needed.
_DEFAULT_HTTP_READ_TIMEOUT_S = 300.0


def _http_timeout() -> httpx.Timeout:
    read_s = float(
        os.environ.get(
            "TOKENFACTORY_HTTP_READ_TIMEOUT_S",
            str(_DEFAULT_HTTP_READ_TIMEOUT_S),
        )
    )
    read_s = max(60.0, read_s)
    connect_s = min(60.0, read_s)
    return httpx.Timeout(read_s, connect=connect_s)


@dataclass(frozen=True)
class OpenAITokenProvider:
    """ChatGPT-backed token provider (gpt-image-2 + local blend for inter-frames).

    ``api_key`` must be the user's key — never pulled from env so the error
    surfaces at the provider boundary, not deep in the pipeline.
    """

    api_key: str
    model: str = _DEFAULT_MODEL

    def generate_candidate(
        self,
        *,
        canvas: tuple[int, int],
        prompt: str,
    ) -> Image.Image:
        png = self._generate_text2img(prompt)
        return _to_canvas(png, canvas)

    def generate_key_pose(
        self,
        *,
        canvas: tuple[int, int],
        reference_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        src_bytes = _pil_to_png_bytes(reference_img)
        png = self._edit_once(src_bytes, prompt)
        return _to_canvas(png, canvas)

    def generate_interframe(
        self,
        *,
        canvas: tuple[int, int],
        source_img: Image.Image,
        prompt: str,
    ) -> Image.Image:
        """Generate an inter-frame from a blended source (high structure lock)."""
        src_bytes = _pil_to_png_bytes(source_img)
        structure_prompt = (
            "Maintain exact character proportions and palette. "
            "Natural fluid motion between two adjacent poses. "
            "No new elements, no text, same style. "
            + prompt
        )
        png = self._edit_once(src_bytes, structure_prompt)
        return _to_canvas(png, canvas)

    def cost_estimate_usd(self, *, n_candidates: int, n_frames: int) -> float:
        return float(n_candidates + n_frames) * _COST_PER_IMAGE_USD

    # ── internal ──

    def _generate_text2img(self, prompt: str) -> bytes:
        # ``response_format`` is not accepted by newer image models (e.g. gpt-image-2);
        # responses may use ``url`` or ``b64_json`` — ``_decode_first`` handles both.
        resp = self._post_json(
            f"{_BASE_URL}/images/generations",
            {
                "model": self.model,
                "prompt": prompt,
                "n": 1,
                "size": _API_SIZE,
                "quality": "low",
            },
        )
        chunk = _decode_first(resp)
        if chunk is None:
            raise RuntimeError("OpenAI returned no image data for text2img.")
        return chunk

    def _edit_once(self, source_png_bytes: bytes, prompt: str) -> bytes:
        src_buf = _to_api_size_bytes(source_png_bytes)
        resp = self._multipart_post(
            f"{_BASE_URL}/images/edits",
            data={
                "model": self.model,
                "prompt": prompt,
                "n": "1",
                "size": _API_SIZE,
            },
            files={"image": ("source.png", src_buf, "image/png")},
        )
        chunk = _decode_first(resp)
        if chunk is None:
            raise RuntimeError("OpenAI returned no image data for edit.")
        return chunk

    def _post_json(self, url: str, payload: dict) -> dict:
        last_exc: Exception | None = None
        wait = _RETRY_BASE_S
        for _attempt in range(_MAX_RETRIES):
            try:
                r = httpx.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=_http_timeout(),
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(_error_body(r))
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            if not r.is_success:
                raise RuntimeError(f"OpenAI API {r.status_code}: {_error_body(r)}")
            return r.json()
        raise RuntimeError(
            f"OpenAI API gave up after {_MAX_RETRIES} retries: {last_exc}"
        )

    def _multipart_post(self, url: str, data: dict, files: dict) -> dict:
        last_exc: Exception | None = None
        wait = _RETRY_BASE_S
        for _attempt in range(_MAX_RETRIES):
            try:
                r = httpx.post(
                    url,
                    data=data,
                    files=files,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=_http_timeout(),
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(_error_body(r))
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            if not r.is_success:
                raise RuntimeError(f"OpenAI API {r.status_code}: {_error_body(r)}")
            return r.json()
        raise RuntimeError(
            f"OpenAI API gave up after {_MAX_RETRIES} retries: {last_exc}"
        )


# ── helpers ──

def _pil_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _to_api_size_bytes(png_bytes: bytes) -> io.BytesIO:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    if img.size != (1024, 1024):
        img = img.resize((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _to_canvas(png_bytes: bytes, canvas: tuple[int, int]) -> Image.Image:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    w, h = canvas
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img


def _decode_first(resp: dict) -> bytes | None:
    for item in resp.get("data", []):
        b64 = item.get("b64_json")
        if b64:
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            r = httpx.get(url, timeout=_http_timeout())
            r.raise_for_status()
            return r.content
    return None


def _error_body(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", "") or r.text[:200]
    except Exception:
        return r.text[:200]

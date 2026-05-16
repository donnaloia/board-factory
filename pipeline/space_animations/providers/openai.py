"""OpenAI / ChatGPT-backed I2V provider.

OpenAI's public Images API (``gpt-image-2``) does **not** ship a true
image-to-video endpoint. To still let users animate a space with their
ChatGPT API key, this provider produces a looping clip in three steps:

  1. A one-shot **vision pass** (``gpt-4o``) reads the source image plus
     the user's motion prompt and emits N concrete destination-frame
     descriptions grounded in what is actually visible (see
     :mod:`_motion_director`). No aesthetic presets — every plan
     follows the user's stated intent.
  2. **One call per candidate** to ``/v1/images/edits`` with that plan
     as the prompt, producing one "destination" still per candidate.
  3. **Locally** interpolating between the source PNG and the returned
     still using ``PIL.Image.blend`` to synthesize the in-between
     frames. The morph runs source → variant → source so the first and
     last frames are always identical, giving a seamless loop before any
     of the strategies in ``space_animations.steps.loop_close`` apply.

That hybrid keeps the per-job OpenAI cost predictable (1 vision call +
N image-edit calls for N candidates) while producing motion tailored to
this specific image and the user's request — instead of generic
brightness pulses or shimmer overlays.

Hard limitation: ``gpt-image-2`` is a still-image model, so step 2
yields a single destination frame and step 3 is a crossfade. True
motion physics (e.g. a fire plume that ejects, arcs, and dissipates)
needs a real image-to-video model — when one lands as a sibling
provider, replace this provider's ``generate`` body with a direct call
to it and drop the vision pass + morph entirely.
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass

import httpx
from PIL import Image

from .base import Clip
from ._motion_director import (
    COST_PER_CALL_USD as _VISION_COST_USD,
    plan_motion_variants,
)


_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-image-2"
_API_SIZE = "1024x1024"  # all gpt-image-2 edits use a fixed canvas size

# Retry config for transient 429 / 5xx — same numbers as boardfactory's
# OpenAI provider so behaviour stays predictable across the app.
_MAX_RETRIES = 5
_RETRY_BASE_S = 5.0
_RETRY_MAX_S = 60.0

# Approximate per-image cost at ``low`` quality (verify against OpenAI
# pricing; this is only used for the UI estimate and for the job cost
# ledger — actual billing happens server-side at OpenAI).
_COST_PER_IMAGE_USD = 0.011


def _compose_edit_prompt(animation_prompt: str, plan: str) -> str:
    """Wrap a per-candidate plan in image-edit framing.

    ``animation_prompt`` is the user's original direction (e.g. "chimera
    breathing fire"). ``plan`` is the image-grounded destination-frame
    description produced by :func:`plan_motion_variants` — falling back
    to ``animation_prompt`` itself when the director was unavailable.

    There is intentionally **no aesthetic preset** here (no glow /
    shimmer / drift); we only add the minimum framing the edit model
    needs to keep composition stable.
    """
    user = (animation_prompt or "").strip()
    plan_text = (plan or "").strip() or user
    parts = ["Same scene, identical composition and palette as the input image."]
    if user:
        parts.append(f"Animator's direction: {user}")
    parts.append(f"Destination still: {plan_text}")
    parts.append(
        "Preserve silhouettes and overall layout of everything not explicitly changed; "
        "no new text, no UI overlays, no watermark."
    )
    return " ".join(parts)


@dataclass(frozen=True)
class OpenAII2VProvider:
    """ChatGPT-backed image-to-video via vision-planned per-candidate edits + local morph.

    Frozen dataclass so the provider is hashable and trivially
    testable. ``api_key`` is required and must be the **user's** key —
    never read from environment so missing-key errors surface at the
    provider boundary rather than mid-pipeline.
    """

    api_key: str
    model: str = _DEFAULT_MODEL
    name: str = "openai"

    @property
    def model_id(self) -> str:
        # Surface that this is hybrid (gpt-image-2 destination + a local
        # morph step) and that a vision pass directed each candidate. A
        # future Sora / true-I2V provider gets its own distinct id when
        # it lands.
        return f"{self.model}/morph+vision"

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
        if not self.api_key:
            raise RuntimeError(
                "OpenAI I2V provider requires the user's OpenAI API key. "
                "Save it in Account → Connections → OpenAI / ChatGPT, "
                "or switch SPACE_ANIMATIONS_PROVIDER=mock in the env."
            )
        if candidates <= 0:
            return []
        if not (animation_prompt or "").strip():
            # Defense in depth: the HTTP route enforces non-empty, but
            # the provider is also a public surface (tests, other
            # callers) so we fail fast rather than invent direction.
            raise RuntimeError(
                "OpenAI I2V provider requires a non-empty animation_prompt; "
                "the web layer enforces this at the route boundary."
            )

        source = Image.open(io.BytesIO(source_png)).convert("RGBA")
        frame_count = max(2, int(round(fps * duration_ms / 1000.0)))

        plans = plan_motion_variants(
            source_png=source_png,
            animation_prompt=animation_prompt,
            n=candidates,
            api_key=self.api_key,
        )

        clips: list[Clip] = []
        for i in range(candidates):
            plan = plans[i] if i < len(plans) else animation_prompt
            edit_prompt = _compose_edit_prompt(animation_prompt, plan)
            variant_png = self._edit_once(source_png, edit_prompt)
            variant = (
                Image.open(io.BytesIO(variant_png))
                .convert("RGBA")
                .resize(source.size, Image.LANCZOS)
            )
            frames = _morph_loop_frames(source, variant, frame_count)
            short_plan = (plan or "").strip().replace("\n", " ")[:80]
            clips.append(
                Clip(
                    frames=frames,
                    fps=fps,
                    seed=seed,
                    notes=f"openai · {short_plan} (gpt-image-2 + vision)",
                )
            )
        return clips

    def cost_estimate(self, *, candidates: int, duration_ms: int) -> float:
        # 1 vision call + N edit calls per job. Duration / fps don't
        # change cost because the morph runs locally.
        return _VISION_COST_USD + float(candidates) * _COST_PER_IMAGE_USD

    # ────────────────────────── helpers ──────────────────────────

    def _edit_once(self, source_png: bytes, prompt: str) -> bytes:
        """One ``/images/edits`` call with the source PNG. Returns PNG bytes."""
        src_buf = _to_api_size(source_png)
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
            raise RuntimeError(
                "OpenAI returned no image data for the edit request "
                "(check organization access to gpt-image-2 / billing)."
            )
        return chunk

    def _multipart_post(self, url: str, data: dict, files: dict) -> dict:
        last_exc: Exception | None = None
        wait = _RETRY_BASE_S
        for _attempt in range(_MAX_RETRIES):
            r = httpx.post(
                url,
                data=data,
                files=files,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=120.0,
            )
            if r.status_code == 429 or r.status_code >= 500:
                last_exc = RuntimeError(_error_body(r))
                time.sleep(min(wait, _RETRY_MAX_S))
                wait *= 2
                continue
            if not r.is_success:
                raise RuntimeError(f"OpenAI API {r.status_code}: {_error_body(r)}")
            return r.json()
        raise RuntimeError(
            f"OpenAI API gave up after {_MAX_RETRIES} attempts: {last_exc}"
        )


# ────────────────────────── module-private helpers ──────────────────────────


def _morph_loop_frames(
    source: Image.Image,
    variant: Image.Image,
    frame_count: int,
) -> list[Image.Image]:
    """Render frames that morph source → variant → source.

    Public for unit testing via ``space_animations.providers.openai``.

    The first and last frames are both ``source``, so the producer
    naturally hands a seamless loop to ``loop_close`` regardless of which
    closure strategy is configured. ``frame_count`` ≥ 2 is required.
    """
    if frame_count < 2:
        raise ValueError(f"frame_count must be >= 2 (got {frame_count})")
    src_rgba = source.convert("RGBA")
    var_rgba = variant.convert("RGBA").resize(src_rgba.size, Image.LANCZOS)
    out: list[Image.Image] = []
    for i in range(frame_count):
        # Triangle wave 0 → 1 → 0 across [0, frame_count - 1].
        # i=0 and i=frame_count-1 both map to alpha 0 → identical to source.
        t = i / (frame_count - 1)
        alpha = 1.0 - abs(1.0 - 2.0 * t)
        # Image.blend wants both images the same mode and size; guaranteed above.
        out.append(Image.blend(src_rgba, var_rgba, alpha))
    return out


def _to_api_size(png_bytes: bytes) -> io.BytesIO:
    """Resize input to gpt-image-2's required 1024×1024 canvas."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    if img.size != (1024, 1024):
        img = img.resize((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _decode_first(resp: dict) -> bytes | None:
    """Pull the first PNG bytes out of an OpenAI Images API response."""
    for item in resp.get("data", []):
        b64 = item.get("b64_json")
        if b64:
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            r = httpx.get(url, timeout=30.0)
            r.raise_for_status()
            return r.content
    return None


def _error_body(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", "") or r.text[:200]
    except Exception:
        return r.text[:200]

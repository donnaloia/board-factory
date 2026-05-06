"""Frame-vision providers.

A ``FrameVisionProvider`` proposes candidate frame segmentations for a
single source image. Each candidate is a triple of (outer ring polygon,
inner hole polygon, confidence score) — ``frames_inference`` then
turns those into ``CandidateGeometry`` (clean masks, snapped bbox,
ring thickness).

Why a separate abstraction (rather than reusing ``PixelArtProvider``)?
The image-art providers know about generate / img2img / inpaint and
return PNG bytes. Vision providers return *structured geometry*, not
images, so the contracts diverge enough that one interface for both
would be misleading. We keep the two abstractions side-by-side.

Phase A in the customization plan ships two concrete implementations:

  * ``OpenAIFrameVision`` — sends the source to GPT-image vision with a
    structured-JSON system prompt, parses (outer, inner) polygon arrays
    from the reply, rasterizes to (outer, inner) masks. This reuses the
    same JSON-mode pattern as ``boardfactory/ops/analyze.py``.
  * ``MockFrameVision`` — returns a deterministic candidate built from
    the same ``derive_masks_from_ring`` helper today's compositor uses.
    Tests run against this so they never need an API key.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from PIL import Image, ImageDraw

from .. import frames as bf_frames

logger = logging.getLogger(__name__)


# ────────────────────────── data shape ──────────────────────────


@dataclass(frozen=True)
class FrameCandidate:
    """One vision candidate, before deterministic cleanup."""

    outer_mask: Image.Image      # L-mode binary at source size
    inner_mask: Image.Image      # L-mode binary at source size
    score: float                 # 0..1, model-reported when available
    notes: str = ""
    model_id: str | None = None
    prompt_hash: str | None = None


# ────────────────────────── interface ──────────────────────────


class FrameVisionProvider(ABC):
    """Implementations propose 1..N candidate frame segmentations."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_id(self) -> str:
        ...

    @abstractmethod
    def segment_frame(
        self,
        source: Image.Image,
        *,
        candidate_count: int = 3,
    ) -> list[FrameCandidate]:
        """Return up to ``candidate_count`` candidates ranked best-first."""

    def cost_estimate(self, candidate_count: int) -> float:
        """USD cost guess for one segmentation call. Free providers return 0."""
        return 0.0


# ────────────────────────── helpers ──────────────────────────


def _polygon_mask(
    size: tuple[int, int], polygon: list[tuple[float, float]]
) -> Image.Image:
    """Rasterize ``polygon`` (normalized 0..1 coords) onto an L-mode mask."""
    w, h = size
    mask = Image.new("L", (w, h), 0)
    if not polygon:
        return mask
    pts = [
        (
            max(0, min(w - 1, int(round(px * w)))),
            max(0, min(h - 1, int(round(py * h)))),
        )
        for (px, py) in polygon
    ]
    if len(pts) < 3:
        return mask
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    return mask


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]


# ────────────────────────── mock ──────────────────────────


class MockFrameVision(FrameVisionProvider):
    """Offline provider — returns deterministic candidates by ring math.

    Hands back ``candidate_count`` candidates with monotonically thicker
    rings around the same axis-aligned center, so tests can verify the
    Atelier candidate-switcher actually changes which one is picked.
    """

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model_id(self) -> str:
        return "mock-frame-v1"

    def segment_frame(
        self,
        source: Image.Image,
        *,
        candidate_count: int = 3,
    ) -> list[FrameCandidate]:
        w, h = source.size
        smallest = min(w, h)
        if smallest <= 4:
            return []
        base = max(2, smallest // 16)
        out: list[FrameCandidate] = []
        for i in range(max(1, candidate_count)):
            ring = base + i * max(1, base // 2)
            ring = min(ring, smallest // 2 - 1)
            if ring <= 0:
                break
            hole, rim = bf_frames.derive_masks_from_ring((w, h), ring)
            # outer = rim ∪ hole = the full bbox of the panel.
            outer = Image.new("L", (w, h), 255)
            inner = hole
            score = 1.0 - (i * 0.1)
            out.append(
                FrameCandidate(
                    outer_mask=outer,
                    inner_mask=inner,
                    score=score,
                    notes=f"mock ring={ring}",
                    model_id=self.model_id,
                    prompt_hash="mock",
                )
            )
        return out

    def cost_estimate(self, candidate_count: int) -> float:
        return 0.0


# ────────────────────────── OpenAI ──────────────────────────


_OPENAI_SYSTEM = (
    "You are a computer-vision module that segments ornamental picture frames "
    "in pixel-art tile images. You respond with valid JSON only — no markdown "
    "fences, no explanation."
)

_OPENAI_USER_TMPL = """The image attached is a single tile from a board-game UI panel ({w}×{h} px).

TASK
Find the decorative outer ring/frame around the central content. There may be
multiple plausible rings (a thin metallic edge AND an outer wooden frame, for
example). For each plausible ring, return BOTH:
  - "outer_polygon": closed polygon tracing the OUTER edge of the rim
  - "inner_polygon": closed polygon tracing the INNER edge of the rim
                     (i.e. the boundary of the central content "hole")

Coordinates MUST be normalized in the range 0.0..1.0 with the origin at the
top-left of the image. The polygons should each have 4..32 vertices and be
ordered (clockwise OR counter-clockwise — pick one and stick to it).

CONFIDENCE
For each candidate, include a "score" in 0.0..1.0 reflecting how confident you
are it is THE intended decorative frame (vs a stray contour or background
element).

LIMITS
Return at most {n} candidates, ordered best-first. If no decorative frame is
visible, return ``{{"candidates": []}}``.

OUTPUT
{{
  "candidates": [
    {{
      "outer_polygon": [[0.02,0.03],[0.98,0.03],[0.98,0.97],[0.02,0.97]],
      "inner_polygon": [[0.10,0.12],[0.90,0.12],[0.90,0.88],[0.10,0.88]],
      "score": 0.92,
      "notes": "outer wood, square corners"
    }}
  ]
}}
"""


class OpenAIFrameVision(FrameVisionProvider):
    """Phase A: GPT-image vision -> JSON polygons -> rasterized masks.

    Uses the chat-completions endpoint with ``response_format=json_object``
    so we can rely on the reply being parseable JSON without parsing
    around markdown fences.
    """

    _API_URL = "https://api.openai.com/v1/chat/completions"
    _MODEL = "gpt-4o"
    _COST_PER_CALL = 0.04   # rough estimate; updated from billing if available

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Save it in Account → Connections → "
                "OpenAI / ChatGPT, or pass api_key= to OpenAIFrameVision()."
            )
        self._model = (model or self._MODEL).strip() or self._MODEL

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model_id(self) -> str:
        return self._model

    def cost_estimate(self, candidate_count: int) -> float:
        return self._COST_PER_CALL

    # ── public API ──

    def segment_frame(
        self,
        source: Image.Image,
        *,
        candidate_count: int = 3,
    ) -> list[FrameCandidate]:
        if candidate_count < 1:
            candidate_count = 1
        candidate_count = min(candidate_count, 5)

        rgb = source.convert("RGB")
        b64 = self._encode_jpeg(rgb)
        prompt_text = _OPENAI_USER_TMPL.format(
            w=rgb.width, h=rgb.height, n=candidate_count
        )
        ph = _prompt_hash(prompt_text + b64[:64])

        body = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": _OPENAI_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        }

        try:
            resp = httpx.post(
                self._API_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"OpenAI vision request failed: {e}") from e

        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise RuntimeError(
                f"OpenAI vision response had unexpected shape: {e}"
            ) from e

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"OpenAI vision returned invalid JSON: {e}\n\nFirst 400 chars:\n"
                f"{content[:400]}"
            ) from e

        return self._decode_candidates(payload, source.size, ph)

    # ── helpers ──

    @staticmethod
    def _encode_jpeg(img: Image.Image, *, max_side: int = 1024) -> str:
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _decode_candidates(
        self,
        payload: dict,
        size: tuple[int, int],
        prompt_hash: str,
    ) -> list[FrameCandidate]:
        candidates_in = payload.get("candidates")
        if not isinstance(candidates_in, list):
            return []
        out: list[FrameCandidate] = []
        for raw in candidates_in:
            if not isinstance(raw, dict):
                continue
            outer = self._poly(raw.get("outer_polygon"))
            inner = self._poly(raw.get("inner_polygon"))
            if outer is None or inner is None:
                continue
            outer_mask = _polygon_mask(size, outer)
            inner_mask = _polygon_mask(size, inner)
            try:
                score = float(raw.get("score", 0.5))
            except (TypeError, ValueError):
                score = 0.5
            score = max(0.0, min(1.0, score))
            notes = str(raw.get("notes") or "")
            out.append(
                FrameCandidate(
                    outer_mask=outer_mask,
                    inner_mask=inner_mask,
                    score=score,
                    notes=notes,
                    model_id=self.model_id,
                    prompt_hash=prompt_hash,
                )
            )
        return out

    @staticmethod
    def _poly(raw) -> list[tuple[float, float]] | None:
        if not isinstance(raw, list) or len(raw) < 3:
            return None
        out: list[tuple[float, float]] = []
        for pt in raw:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            try:
                x = float(pt[0])
                y = float(pt[1])
            except (TypeError, ValueError):
                return None
            out.append((x, y))
        return out


# ────────────────────────── factory ──────────────────────────


def get_frame_vision_provider(
    *,
    name: str | None = None,
    openai_api_key: str | None = None,
) -> FrameVisionProvider:
    """Return the configured frame-vision provider.

    Resolution order:
      1. ``name`` argument if non-empty.
      2. ``BOARDFACTORY_FRAME_VISION`` env var.
      3. Default to ``"mock"`` so tests Just Work without keys; production
         callers pass ``name="openai"`` explicitly.
    """
    resolved = (name or os.environ.get("BOARDFACTORY_FRAME_VISION", "mock")).lower()
    if resolved in ("mock", ""):
        return MockFrameVision()
    if resolved == "openai":
        return OpenAIFrameVision(api_key=openai_api_key)
    raise ValueError(
        f"Unknown FrameVisionProvider {resolved!r}. "
        "Set BOARDFACTORY_FRAME_VISION to 'mock' or 'openai'."
    )


__all__ = [
    "FrameCandidate",
    "FrameVisionProvider",
    "MockFrameVision",
    "OpenAIFrameVision",
    "get_frame_vision_provider",
]

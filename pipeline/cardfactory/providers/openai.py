"""OpenAI card provider — uses ``gpt-image-2`` inpainting.

Chrome candidates and card illustrations are both produced via the
``/v1/images/edits`` endpoint with RGBA masks.

Notes:
- Chrome uses a white source; prompts add pixel discipline + palette clauses.
- Illustration uses the committed **frame** resized to 1024² as the edit
  source when ``style_reference`` is set (``input_fidelity=high``), so the
  model respects hole edges and palette context; still masked to ``M_art``.
- API returns 1024²; the card assembly step resizes illustration with
  ``NEAREST`` + palette quantize for pixel cohesion with the frame.
- **Final unify** (optional, env): full composited card → ``images/edits``
  with **no mask** (whole-image img2img), ``input_fidelity=high``, and a
  tight “cohesion only” prompt — then resize back to canvas.
"""

from __future__ import annotations

import base64
import io

import httpx
from PIL import Image

from ..config import (
    CHROME_INTERIOR_VALUE_AND_ALPHA_LEAD,
    PIXEL_DISCIPLINE_CHROME,
    PIXEL_DISCIPLINE_ILLUSTRATION,
    UNIFY_FINISHED_CARD_PROMPT,
    SINGLE_PASS_INPAINT_PROMPT_LEAD,
)
from ..steps.prompt_extra import format_palette_clause


_API_URL = "https://api.openai.com/v1/images/edits"
_MODEL = "gpt-image-2"
_OUTPUT_SIZE = "1024x1024"
_QUALITY = "low"


class OpenAICardProvider:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required for OpenAICardProvider")
        self._api_key = api_key

    def model_id(self) -> str:
        return _MODEL

    # ── internal helpers ──

    def _png_bytes(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _error_body(resp: httpx.Response) -> str:
        try:
            return resp.json().get("error", {}).get("message", "") or resp.text[:500]
        except Exception:
            return resp.text[:500]

    @staticmethod
    def _decode_first_image(resp_json: dict) -> Image.Image:
        """``images/edits`` may return ``b64_json`` or ``url`` depending on request flags."""
        for item in resp_json.get("data", []) or []:
            b64 = item.get("b64_json")
            if b64:
                raw = base64.b64decode(b64)
                return Image.open(io.BytesIO(raw)).convert("RGBA")
            url = item.get("url")
            if url:
                r = httpx.get(url, timeout=120.0)
                r.raise_for_status()
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
        raise RuntimeError(
            "OpenAI returned no image in the edits response — check API access / billing."
        )

    def _call_edits(
        self,
        source_img: Image.Image,
        mask_img: Image.Image,
        prompt: str,
        *,
        input_fidelity: str | None = None,
    ) -> Image.Image:
        """One ``/v1/images/edits`` call; returns RGBA PIL at API resolution."""
        src_buf = io.BytesIO(self._png_bytes(source_img.convert("RGBA")))
        src_buf.seek(0)
        msk_buf = io.BytesIO(self._png_bytes(mask_img.convert("RGBA")))
        msk_buf.seek(0)

        data: dict[str, str] = {
            "model": _MODEL,
            "prompt": prompt,
            "n": "1",
            "size": _OUTPUT_SIZE,
            "quality": _QUALITY,
        }
        if input_fidelity:
            data["input_fidelity"] = input_fidelity

        with httpx.Client(timeout=120) as client:
            resp = client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={
                    "image": ("source.png", src_buf, "image/png"),
                    "mask": ("mask.png", msk_buf, "image/png"),
                },
                data=data,
            )
        if not resp.is_success:
            raise RuntimeError(
                f"OpenAI images/edits {resp.status_code}: {self._error_body(resp)}"
            )
        return self._decode_first_image(resp.json())

    def _call_edits_image_only(
        self,
        source_img: Image.Image,
        prompt: str,
        *,
        input_fidelity: str | None = "high",
    ) -> Image.Image:
        """``/v1/images/edits`` with image only (no mask) — img2img / full-frame refine."""
        src_buf = io.BytesIO(self._png_bytes(source_img.convert("RGBA")))
        src_buf.seek(0)
        data: dict[str, str] = {
            "model": _MODEL,
            "prompt": prompt,
            "n": "1",
            "size": _OUTPUT_SIZE,
            "quality": _QUALITY,
        }
        if input_fidelity:
            data["input_fidelity"] = input_fidelity

        with httpx.Client(timeout=120) as client:
            resp = client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data=data,
                files={"image": ("card.png", src_buf, "image/png")},
            )
        if not resp.is_success:
            raise RuntimeError(
                f"OpenAI images/edits {resp.status_code}: {self._error_body(resp)}"
            )
        return self._decode_first_image(resp.json())

    # ── provider protocol ──

    def generate_chrome_candidate(
        self,
        *,
        canvas: tuple[int, int],
        m_chrome_paint: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Generate chrome using inpainting on a white source canvas."""
        w, h = canvas
        api_size = (1024, 1024)
        source = Image.new("RGBA", api_size, (255, 255, 255, 255))

        mask_resized = m_chrome_paint.resize(api_size, Image.LANCZOS).convert("L")
        mask_rgba = Image.new("RGBA", api_size, (0, 0, 0, 255))
        mask_rgba.putalpha(Image.eval(mask_resized, lambda v: 255 - v))

        full_prompt = (
            PIXEL_DISCIPLINE_CHROME
            + CHROME_INTERIOR_VALUE_AND_ALPHA_LEAD
            + format_palette_clause(palette_colors)
            + prompt
        )
        result = self._call_edits(source, mask_rgba, full_prompt)

        if result.size != (w, h):
            result = result.resize((w, h), Image.LANCZOS)
        return result

    def generate_illustration(
        self,
        *,
        canvas: tuple[int, int],
        m_art: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
        style_reference: Image.Image | None = None,
    ) -> Image.Image:
        """Generate card illustration inside ``m_art`` via inpainting."""
        api_size = (1024, 1024)
        if style_reference is not None:
            source = style_reference.convert("RGBA")
            if source.size != api_size:
                source = source.resize(api_size, Image.LANCZOS)
            fidelity: str | None = "high"
        else:
            source = Image.new("RGBA", api_size, (255, 255, 255, 255))
            fidelity = None

        mask_resized = m_art.resize(api_size, Image.LANCZOS).convert("L")
        mask_rgba = Image.new("RGBA", api_size, (0, 0, 0, 255))
        mask_rgba.putalpha(Image.eval(mask_resized, lambda v: 255 - v))

        full_prompt = (
            PIXEL_DISCIPLINE_ILLUSTRATION
            + format_palette_clause(palette_colors)
            + prompt
        )
        try:
            return self._call_edits(
                source, mask_rgba, full_prompt, input_fidelity=fidelity
            )
        except RuntimeError:
            if not fidelity:
                raise
            # Some orgs/API versions reject ``input_fidelity`` on edits — retry without.
            return self._call_edits(source, mask_rgba, full_prompt)

    def paint_integrated_card(
        self,
        *,
        canvas: tuple[int, int],
        source_image: Image.Image,
        edit_mask: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
        style_reference: Image.Image | None = None,
    ) -> Image.Image:
        """Single-pass interior: inpaint art ∪ stats with frame already in ``source_image``."""
        w, h = canvas
        api_size = (1024, 1024)
        src = source_image.convert("RGBA")
        if src.size != api_size:
            src = src.resize(api_size, Image.LANCZOS)
        fidelity: str | None = "high"

        mask_resized = edit_mask.resize(api_size, Image.LANCZOS).convert("L")
        mask_rgba = Image.new("RGBA", api_size, (0, 0, 0, 255))
        mask_rgba.putalpha(Image.eval(mask_resized, lambda v: 255 - v))

        full_prompt = (
            PIXEL_DISCIPLINE_ILLUSTRATION
            + SINGLE_PASS_INPAINT_PROMPT_LEAD
            + format_palette_clause(palette_colors)
            + prompt
        )
        try:
            out = self._call_edits(
                src, mask_rgba, full_prompt, input_fidelity=fidelity
            )
        except RuntimeError:
            out = self._call_edits(src, mask_rgba, full_prompt)

        if out.size != (w, h):
            out = out.resize((w, h), Image.LANCZOS)
        return out.convert("RGBA")

    def unify_finished_card(
        self,
        *,
        card: Image.Image,
        canvas: tuple[int, int],
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Conservative whole-card cohesion pass (no inpaint mask — high fidelity)."""
        w, h = canvas
        api_size = (1024, 1024)
        src = card.convert("RGBA")
        if src.size != api_size:
            src = src.resize(api_size, Image.LANCZOS)

        prompt = (
            UNIFY_FINISHED_CARD_PROMPT
            + format_palette_clause(palette_colors)
        )
        try:
            out = self._call_edits_image_only(src, prompt, input_fidelity="high")
        except RuntimeError:
            out = self._call_edits_image_only(src, prompt, input_fidelity=None)

        if out.size != (w, h):
            out = out.resize((w, h), Image.LANCZOS)
        return out.convert("RGBA")

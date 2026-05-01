"""Mockup analysis via GPT-4o vision — auto-fills catalog prompts.

One HTTP call sends the full board mockup plus a structured JSON template
describing every region by pixel coordinates. GPT-4o returns a filled-in
JSON object with:

  - style_prompt  : overall theme / art-style sentence (→ catalog.style.prompt)
  - designs       : {design_id: prompt, ...}  (→ board_spaces.designs[].prompt)
  - panels        : {panel_id:  prompt, ...}  (→ feature_panels.panels[].prompt)
  - centerpiece   : prompt string             (→ catalog.centerpiece.prompt)

The caller (pipeline_adapters.analyze_adapter) is responsible for writing
the results back to catalog.yml on disk.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import httpx
from PIL import Image

from ..schemas import Catalog
from .progress import ProgressSink


# ────────────────────────── constants ──────────────────────────

_API_URL = "https://api.openai.com/v1/chat/completions"
_MODEL   = "gpt-4o"

_SYSTEM = (
    "You are a board-game art director. "
    "Your job is to write terse, vivid generation prompts for pixel-art assets. "
    "Respond with valid JSON only — no markdown fences, no explanation."
)

# Cost ceiling so the caller can log an estimate (actual billed by OpenAI).
# gpt-4o: $2.50/1M input + $10.00/1M output; detail=high image ≈ 1500 tokens.
COST_ESTIMATE_USD = 0.08


# ────────────────────────── image helpers ──────────────────────────


def _encode_image(img: Image.Image, max_w: int = 1920) -> str:
    """Return a base64-encoded JPEG string for the OpenAI vision API."""
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def _crop_b64(img: Image.Image, bbox: tuple[int, int, int, int]) -> str:
    """Crop a region and return it base64-encoded for the vision API."""
    x1, y1, x2, y2 = bbox
    crop = img.crop((x1, y1, x2, y2))
    return _encode_image(crop, max_w=512)


# ────────────────────────── OpenAI call ──────────────────────────


def _chat(openai_key: str, messages: list[dict], max_tokens: int = 3000) -> str:
    resp = httpx.post(
        _API_URL,
        json={
            "model": _MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        },
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json",
        },
        timeout=90.0,
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(
            f"OpenAI API error {resp.status_code}: {body or resp.text[:200]}"
        ) from e
    return resp.json()["choices"][0]["message"]["content"].strip()


# ────────────────────────── prompt builder ──────────────────────────


def _build_prompt(catalog: Catalog, board_w: int, board_h: int) -> str:
    """Build the structured analysis prompt with all item IDs + spatial hints."""
    designs = catalog.all_space_designs()
    panels  = catalog.all_panels()
    cp      = catalog.centerpiece

    # ── space designs: describe each by its first position's pixel coords ──
    design_entries: list[str] = []
    for d in designs:
        if d.positions:
            try:
                x, y, w, h = catalog.board_spaces.resolve_position(d.positions[0])
                hint = f"x={x}-{x+w}, y={y}-{y+h}"
                # also list extra positions so GPT understands it's a repeating tile
                if len(d.positions) > 1:
                    hint += f" (+{len(d.positions)-1} identical positions)"
            except Exception:
                hint = "position unknown"
        else:
            hint = "position unknown"
        design_entries.append(f'    "{d.id}": ""  // space tile at {hint}')

    # ── panels: exact bbox ──
    panel_entries: list[str] = []
    for p in panels:
        x1, y1, x2, y2 = p.bbox
        panel_entries.append(
            f'    "{p.id}": ""  // panel region x={x1}-{x2}, y={y1}-{y2}'
        )

    # ── centerpiece ──
    cx1, cy1, cx2, cy2 = cp.bbox
    cp_hint = f"x={cx1}-{cx2}, y={cy1}-{cy2}"

    designs_json = "{\n" + ",\n".join(design_entries) + "\n  }"
    panels_json  = "{\n" + ",\n".join(panel_entries)  + "\n  }"

    return f"""This is a board-game mockup image ({board_w}×{board_h} pixels, standard Monopoly-style perimeter layout).

Board regions:
• Perimeter (TOP): 12 cells across the top edge, y≈0-180
• Perimeter (BOTTOM): 12 cells across the bottom edge, y≈{board_h-180}-{board_h}
• Perimeter (LEFT): 5 stacked cells on the left, x≈0-180
• Perimeter (RIGHT): 5 stacked cells on the right, x≈{board_w-180}-{board_w}
• CENTER ARTWORK: large region at x={cx1}-{cx2}, y={cy1}-{cy2}
• INTERIOR PANELS: 12 rectangular panels (260×240px each) flanking the center on both sides

TASK: Fill every empty string "" in the JSON below with a SHORT pixel-art generation prompt (max 15 words) describing the visual content at those coordinates. For "style_prompt", write 1-2 sentences capturing the board's overall theme, art style, color palette (name several distinct accent colors visible in the mockup), and mood — not a monochrome summary unless the mockup truly is monochrome.

Return ONLY the completed JSON — nothing else.

{{
  "style_prompt": "",
  "designs": {designs_json},
  "panels": {panels_json},
  "centerpiece": ""  // center artwork at {cp_hint}
}}"""


# ────────────────────────── main entrypoint ──────────────────────────


def analyze_mockup(
    catalog: Catalog,
    mockup_path: Path,
    openai_key: str,
    sink: ProgressSink,
) -> dict:
    """Send the mockup to GPT-4o and return filled-in prompt suggestions.

    Returns:
        {
            "style_prompt": str,
            "designs":      {id: str, ...},
            "panels":       {id: str, ...},
            "centerpiece":  str,
        }

    Raises RuntimeError on API errors or invalid JSON responses.
    """
    sink.start("analyze mockup with GPT-4o vision", total=4)
    sink.log(f"loading mockup: {mockup_path}")

    mockup = Image.open(mockup_path).convert("RGB")
    w, h = mockup.size
    sink.step("mockup loaded")

    prompt_text = _build_prompt(catalog, w, h)
    sink.log(f"prompt: {len(prompt_text)} chars, {len(catalog.all_space_designs())} designs, "
             f"{len(catalog.all_panels())} panels")

    b64 = _encode_image(mockup)
    sink.step("image encoded")

    sink.log("→ calling GPT-4o vision (this takes ~10-20s)…")
    messages = [
        {"role": "system", "content": _SYSTEM},
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
    ]

    raw = _chat(openai_key, messages)
    sink.step("vision response received")
    sink.log(f"← {len(raw)} chars received")

    # Parse + normalise ────────────────────────────────────────────────────────
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"GPT-4o returned invalid JSON: {e}\n\nFirst 400 chars:\n{raw[:400]}"
        ) from e

    design_ids = [d.id for d in catalog.all_space_designs()]
    panel_ids  = [p.id for p in catalog.all_panels()]

    designs = result.get("designs") or {}
    panels  = result.get("panels")  or {}

    # Fill any keys GPT missed with empty string so the adapter can write safely.
    for did in design_ids:
        designs.setdefault(did, "")
    for pid in panel_ids:
        panels.setdefault(pid, "")

    out = {
        "style_prompt": str(result.get("style_prompt") or ""),
        "designs":      {k: str(v) for k, v in designs.items()},
        "panels":       {k: str(v) for k, v in panels.items()},
        "centerpiece":  str(result.get("centerpiece") or ""),
    }

    n_filled = (
        sum(1 for v in out["designs"].values() if v)
        + sum(1 for v in out["panels"].values() if v)
        + bool(out["centerpiece"])
        + bool(out["style_prompt"])
    )
    sink.step("done")
    sink.log(f"filled {n_filled} / {len(design_ids)+len(panel_ids)+2} prompt fields")

    return out

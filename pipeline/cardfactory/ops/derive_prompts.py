"""Derive per-card slot prompts from a linked board (§6.7).

One GPT-4o call receives:
- board catalog excerpts (space kinds, labels, flavor/theme text)
- the board's style sheet / generation block
- a palette summary (dominant color names)
- optional mockup caption or theme sentence

And returns structured per-slot payloads: illustration prompts, stat-line
strings, and titles — ready to populate ``card_slot_records`` rows.
"""

from __future__ import annotations

import json

import httpx

from .progress import ProgressSink


_API_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-4o"

_SYSTEM = (
    "You are a tabletop game card art director. "
    "Your job is to write concise, vivid illustration prompts and short flavor stat-lines "
    "for playing-card-style assets. "
    "Respond with valid JSON only — no markdown fences, no explanation."
)

_USER_TEMPLATE = """
Given the following board game context, generate {slot_count} card payloads.

=== BOARD STYLE ===
{style_prompt}

=== PALETTE SUMMARY ===
{palette_summary}

=== BOARD CATALOG EXCERPTS ===
{catalog_excerpt}

Respond with a JSON array of exactly {slot_count} objects, one per card slot (0-indexed).
Each object must have:
  "slot_index":           integer (0 to {slot_count_minus_1})
  "title":                short card name (2–4 words)
  "illustration_prompt":  vivid art direction for the card interior (1–2 sentences)
  "stat_lines":           list of 1–3 short strings like "Attack +2", "Speed 3", "Rare"
""".strip()


def _palette_summary(palette_json: str | None) -> str:
    if not palette_json:
        return "No palette available — use the board style prompt for color guidance."
    try:
        colors: list[list[int]] = json.loads(palette_json)
        sample = colors[:6]
        parts = [f"rgb({r},{g},{b})" for r, g, b in sample]
        return "Dominant colors: " + ", ".join(parts)
    except Exception:
        return "Palette available but unreadable."


def _catalog_excerpt(catalog: dict | None) -> str:
    """Extract a concise text summary from a board catalog dict."""
    if not catalog:
        return "No catalog available."
    lines: list[str] = []

    style = catalog.get("style") or {}
    if isinstance(style, dict) and style.get("prompt"):
        lines.append(f"Style: {style['prompt']}")

    spaces = catalog.get("board_spaces") or {}
    designs = spaces.get("designs") or []
    if isinstance(designs, list):
        for d in designs[:8]:
            if isinstance(d, dict):
                label = d.get("label") or d.get("id") or ""
                prompt = d.get("prompt") or ""
                if label or prompt:
                    lines.append(f"Space '{label}': {prompt}")

    cp = catalog.get("centerpiece") or {}
    if isinstance(cp, dict) and cp.get("prompt"):
        lines.append(f"Centerpiece: {cp['prompt']}")

    return "\n".join(lines) if lines else "No catalog details available."


def derive_slot_prompts(
    *,
    slot_count: int,
    style_prompt: str,
    palette_json: str | None,
    catalog: dict | None,
    openai_key: str,
    sink: ProgressSink,
) -> list[dict]:
    """Call GPT-4o to produce structured per-slot payloads.

    Returns a list of dicts (one per slot) with keys ``slot_index``,
    ``title``, ``illustration_prompt``, ``stat_lines``.
    Falls back to numbered placeholders on any error so the pipeline
    does not block the user from continuing.
    """
    sink.emit("derive_prompts", "calling GPT-4o for slot payloads", pct=10)

    user_msg = _USER_TEMPLATE.format(
        slot_count=slot_count,
        slot_count_minus_1=slot_count - 1,
        style_prompt=style_prompt or "No style prompt set.",
        palette_summary=_palette_summary(palette_json),
        catalog_excerpt=_catalog_excerpt(catalog),
    )

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {openai_key}"},
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.8,
                },
            )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)

        # Accept both {"slots": [...]} and bare array
        if isinstance(parsed, list):
            payloads = parsed
        elif isinstance(parsed, dict):
            payloads = next(
                (v for v in parsed.values() if isinstance(v, list)),
                [],
            )
        else:
            payloads = []

        # Normalise and validate each entry
        result: list[dict] = []
        for i in range(slot_count):
            entry = payloads[i] if i < len(payloads) else {}
            result.append(
                {
                    "slot_index": i,
                    "title": str(entry.get("title") or f"Card {i + 1}"),
                    "illustration_prompt": str(
                        entry.get("illustration_prompt") or f"Illustration for card {i + 1}."
                    ),
                    "stat_lines": [
                        str(s) for s in (entry.get("stat_lines") or [])
                    ],
                    "prompt_source": "agent",
                }
            )
        sink.emit("derive_prompts", f"received {len(result)} slot payloads", pct=100)
        return result

    except Exception as exc:
        sink.emit("derive_prompts", f"GPT-4o call failed ({exc}); using placeholders", pct=100)
        return [
            {
                "slot_index": i,
                "title": f"Card {i + 1}",
                "illustration_prompt": f"A vivid pixel-art illustration for card {i + 1}.",
                "stat_lines": ["Attack +1", "Defense 2"],
                "prompt_source": "agent",
            }
            for i in range(slot_count)
        ]

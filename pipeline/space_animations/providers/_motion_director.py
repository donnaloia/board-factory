"""Vision pass that turns a free-form animation prompt into N concrete,
image-grounded edit descriptions — one per candidate.

This is the "auto-direction" half of the OpenAI space-animation provider.
The user types something like ``"chimera breathing fire"``; we send the
source PNG plus the user text to ``gpt-4o`` and ask for N distinct
destination-frame descriptions tailored to what is actually visible in
the source image. Each plan then drives one ``gpt-image-2`` edit call in
:mod:`openai`.

Why a vision pass rather than fixed presets:

* Presets (glow / shimmer / drift) ignore what the image is and what the
  user asked for, so a chimera prompt would still come back with a
  glow-pulse variant — the opposite of what the user wanted.
* The director is allowed to read pixels, so it can ground the motion in
  visible elements ("open the central jaws and add an orange flame
  plume jetting right") instead of generic motion language.

On any failure (network, parsing, short list) we fall back to repeating
the raw user prompt N times — the job never blocks on the director.
"""

from __future__ import annotations

import base64
import json

import httpx

_API_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-4o"
_TIMEOUT_S = 60.0

#: Approximate per-call cost: ~1500 input tokens (image at low detail +
#: short text) and ~200 output tokens at gpt-4o pricing. Surfaced via
#: ``COST_PER_CALL_USD`` so :class:`OpenAII2VProvider` can fold it into
#: its job cost estimate.
COST_PER_CALL_USD = 0.005

_SYSTEM = (
    "You are a motion director for a tabletop board-game UI panel. "
    "You receive ONE source image and a short user description of the motion they want. "
    "Your job: emit N distinct concrete \"destination frame\" descriptions that an image-edit "
    "model can apply to the source. Each plan must be grounded in what is actually visible in "
    "the source image (refer to specific elements you can see), express the motion the user asked "
    "for, and read as a SINGLE still pose — not as a multi-step sequence. The image-edit step will "
    "produce one still per plan and we will crossfade between the source and that still. "
    "Respond with valid JSON only — no markdown fences, no commentary."
)

_USER_TEMPLATE = (
    "User-requested motion: {user}\n\n"
    "Produce {n} distinct interpretations. Each must:\n"
    "- describe a SINGLE destination still frame (the apex of the motion)\n"
    "- name the specific element(s) in the source image that change\n"
    "- preserve overall composition, palette, and silhouette of everything not explicitly changed\n"
    "- differ from the other interpretations (different scale, direction, or focal element)\n\n"
    "Respond as JSON in this exact shape: {{\"plans\": [\"...\", \"...\", ...]}} "
    "with exactly {n} entries."
)


def plan_motion_variants(
    *,
    source_png: bytes,
    animation_prompt: str,
    n: int,
    api_key: str,
) -> list[str]:
    """Return N motion-direction plans, one per candidate.

    Falls back to ``[animation_prompt] * n`` on any failure so the job
    never blocks on the director.
    """
    if n <= 0:
        return []
    fallback = [animation_prompt] * n
    if not (api_key or "").strip():
        return fallback
    if not (animation_prompt or "").strip():
        return fallback

    image_data_url = (
        "data:image/png;base64," + base64.b64encode(source_png).decode("ascii")
    )
    body = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _USER_TEMPLATE.format(
                            user=animation_prompt.strip(), n=n
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url, "detail": "low"},
                    },
                ],
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.9,
    }
    try:
        with httpx.Client(timeout=_TIMEOUT_S) as client:
            r = client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return fallback

    plans = _parse_plans(content, n)
    if plans is None:
        return fallback
    return plans


def _parse_plans(content: str, n: int) -> list[str] | None:
    """Parse a JSON payload from the director into N plans, or ``None``.

    Accepts either ``{"plans": [...]}`` or a bare JSON array. Empty
    entries are dropped; if the model returned fewer than ``n`` plans we
    cycle the available ones so callers always get exactly ``n``.
    """
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    if isinstance(parsed, dict):
        plans_raw = parsed.get("plans")
        if plans_raw is None:
            plans_raw = next(
                (v for v in parsed.values() if isinstance(v, list)), None
            )
    elif isinstance(parsed, list):
        plans_raw = parsed
    else:
        plans_raw = None
    if not isinstance(plans_raw, list):
        return None
    plans = [str(p).strip() for p in plans_raw if str(p).strip()]
    if not plans:
        return None
    if len(plans) < n:
        return [plans[i % len(plans)] for i in range(n)]
    return plans[:n]

"""Compose OpenAI Images prompts for AI mockup generation on the setup page.

Image models cannot follow pixel-perfect geometry; we inject a short **layout
intent** derived from the relational catalog so the mockup roughly matches
perimeter spaces, feature panels, and centerpiece zoning before style lock.
"""

from __future__ import annotations

import math
from typing import Any


def layout_context_for_mockup(catalog: dict[str, Any]) -> str:
    """Return a concise English paragraph (may be empty if catalog is sparse)."""
    bs = catalog.get("board_spaces") or {}
    designs = bs.get("designs") or []
    n_designs = len(designs)
    n_positions = sum(len(d.get("positions") or []) for d in designs)

    fp = catalog.get("feature_panels") or {}
    panels = fp.get("panels") or []
    n_panels = len(panels)

    size = catalog.get("board_size") or [1920, 1080]
    try:
        w, h = int(size[0]), int(size[1])
    except (IndexError, TypeError, ValueError):
        w, h = 1920, 1080
    if w <= 0 or h <= 0:
        w, h = 1920, 1080

    gcd = math.gcd(w, h)
    rw, rh = w // gcd, h // gcd

    parts: list[str] = [
        f"Composition hint (approximate — use as soft guidance, not exact pixels): "
        f"overall canvas shape about {w}×{h} pixels ({rw}:{rh} aspect). "
        f"Lay out roughly {n_positions} board-space / perimeter cells "
        f"using {n_designs} distinct space art designs around the edges or track, "
        f"{n_panels} illustrated functional feature-panel zones "
        f"(UI-style rectangles for cards or UI spaces), "
        f"and one prominent central centerpiece play area that dominates the middle. "
        f"Keep zones visually separated so the board reads as a coherent tabletop game."
    ]
    return " ".join(parts)


def style_snippet_from_catalog(catalog: dict[str, Any], *, max_chars: int = 220) -> str:
    """Optional style brief from ``catalog.style.prompt`` for tone continuity."""
    style = catalog.get("style") or {}
    raw = (style.get("prompt") or "").strip()
    if not raw:
        return ""
    if len(raw) > max_chars:
        raw = raw[: max_chars - 1].rstrip() + "…"
    return f' Overall art direction (match mood and palette): "{raw}"'


def compose_mockup_image_prompt(
    user_prompt: str,
    catalog: dict[str, Any],
    *,
    framing_suffix: str,
) -> str:
    """Merge user text + derived layout + optional style line + fixed framing."""
    layout = layout_context_for_mockup(catalog)
    style_bit = style_snippet_from_catalog(catalog)
    # Order: user intent first (strongest), then layout/style hints, then product framing.
    return (user_prompt.strip() + " " + layout + style_bit + framing_suffix).strip()

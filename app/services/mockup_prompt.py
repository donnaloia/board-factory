"""Compose OpenAI Images prompts for AI mockup generation on the setup page.

Image models cannot follow pixel-perfect geometry; we inject a short **layout
intent** derived from the relational catalog so the mockup roughly matches
perimeter spaces, feature panels, and centerpiece zoning before style lock.
"""

from __future__ import annotations

import math
from typing import Any

# Shared with generate-mockup framing — reinforces orthographic layout + no text.
_MOCKUP_LAYOUT_DISCIPLINE = (
    "Layout discipline: flat orthographic top-down view of one rectangular tabletop "
    "game board, no perspective tilt, no fisheye, no 3D camera angle. "
    "Readable zones only: perimeter track cells, a clearly separated central "
    "illustration/play area, and distinct inner UI or panel/card rectangles "
    "flanking that center — not one full-bleed painting covering the entire canvas. "
    "Do not merge left and right functional columns into a single ambiguous mass; "
    "keep vertical strips and the middle column visually distinct. "
    "No text, letters, numbers, watermarks, or logos."
)


def _layout_counts(layout: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return (top_row, bottom_row, left_col, right_col) counts from catalog layout."""

    def _count(name: str) -> int:
        row = layout.get(name)
        if not row or not isinstance(row, dict):
            return 0
        try:
            return max(0, int(row.get("count", 0)))
        except (TypeError, ValueError):
            return 0

    return (
        _count("top_row"),
        _count("bottom_row"),
        _count("left_col"),
        _count("right_col"),
    )


def _panel_left_right_counts(panels: list[dict[str, Any]], board_w: int) -> tuple[int | None, int | None]:
    """Split panels by bbox center vs board midpoint; returns (left, right) or (None, None)."""
    if not panels or board_w <= 0:
        return None, None
    mid = board_w / 2.0
    left = right = 0
    unknown = 0
    for p in panels:
        bb = p.get("bbox")
        if not isinstance(bb, (list, tuple)) or len(bb) < 4:
            unknown += 1
            continue
        try:
            x1, _, x2, _ = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
        except (TypeError, ValueError):
            unknown += 1
            continue
        c = (x1 + x2) / 2.0
        if c < mid:
            left += 1
        else:
            right += 1
    if unknown > 0 and left + right == 0:
        return None, None
    return left, right


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

    layout = bs.get("layout") or {}
    if not isinstance(layout, dict):
        layout = {}
    tr, br, lc, rc = _layout_counts(layout)

    perimeter_parts: list[str] = []
    if tr:
        perimeter_parts.append(f"{tr} along the top edge")
    if br:
        perimeter_parts.append(f"{br} along the bottom edge")
    if lc:
        perimeter_parts.append(f"{lc} along the left edge")
    if rc:
        perimeter_parts.append(f"{rc} along the right edge")
    perimeter_hint = ""
    if perimeter_parts:
        perimeter_hint = " Perimeter track (approximate counts): " + ", ".join(perimeter_parts) + "."

    pl, pr = _panel_left_right_counts(panels if isinstance(panels, list) else [], w)
    if pl is not None and pr is not None and (pl + pr) > 0:
        panel_hint = (
            f" Inner functional UI panel zones: about {pl} on the left half of the board "
            f"and {pr} on the right half ({n_panels} panel regions total), "
            f"as rectangular game-UI spaces flanking the center."
        )
    elif n_panels:
        panel_hint = (
            f" {n_panels} distinct rectangular functional panel or card UI zones "
            f"in the inner field, flanking the central area."
        )
    else:
        panel_hint = ""

    cp = catalog.get("centerpiece") or {}
    cp_bbox = cp.get("bbox") if isinstance(cp, dict) else None
    centerpiece_hint = ""
    if isinstance(cp_bbox, (list, tuple)) and len(cp_bbox) >= 4:
        try:
            x1, y1, x2, y2 = int(cp_bbox[0]), int(cp_bbox[1]), int(cp_bbox[2]), int(cp_bbox[3])
            centerpiece_hint = (
                f" Reserve a dominant central illustration band roughly "
                f"x={x1}–{x2}, y={y1}–{y2} on this {w}×{h} canvas for the centerpiece "
                f"(keep edge tracks for perimeter spaces outside this middle)."
            )
        except (TypeError, ValueError):
            centerpiece_hint = (
                " One large central focal region for centerpiece artwork, "
                "with perimeter and side zones kept visually separate."
            )
    else:
        centerpiece_hint = (
            " One large central focal region for centerpiece artwork, "
            "with perimeter and side zones kept visually separate."
        )

    counts_hint = (
        f"Composition hint (soft guidance — align zones coherently, not pixel-perfect): "
        f"canvas about {w}×{h} pixels ({rw}:{rh} aspect). "
        f"Roughly {n_positions} perimeter/board-space cells in "
        f"{n_designs} distinct space-art designs."
        f"{perimeter_hint}"
        f"{panel_hint}"
        f"{centerpiece_hint}"
        f" Unified lighting and palette across the whole board."
    )

    return _MOCKUP_LAYOUT_DISCIPLINE + " " + counts_hint


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

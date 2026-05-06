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
    "illustration/play area, and twelve distinct inner functional UI/card rectangles "
    "(four vertical columns × three stacked rows between perimeter and center) — "
    "not one full-bleed painting covering the canvas. "
    "Do not merge the four side columns into two large murals; each slot stays its own "
    "readable rectangle. No text, letters, numbers, watermarks, or logos."
)

# Human labels when clustering resolves exactly four panel columns (standard catalog).
_FOUR_COL_LABELS = (
    "outer-left strip (toward the perimeter)",
    "inner-left strip (flush beside the centerpiece)",
    "inner-right strip (flush beside the centerpiece)",
    "outer-right strip (toward the perimeter)",
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


def _panel_bbox_tuple(p: dict[str, Any]) -> tuple[int, int, int, int] | None:
    bb = p.get("bbox")
    if not isinstance(bb, (list, tuple)) or len(bb) < 4:
        return None
    try:
        return (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3]))
    except (TypeError, ValueError):
        return None


def _cluster_panel_columns(
    panels: list[dict[str, Any]],
    board_w: int,
) -> list[list[dict[str, Any]]]:
    """Group panels into vertical columns by bbox x-center (standard board: 4×3 grid)."""
    entries: list[tuple[dict[str, Any], tuple[int, int, int, int]]] = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        t = _panel_bbox_tuple(p)
        if t is None:
            continue
        entries.append((p, t))
    if not entries:
        return []

    def x_center(bb: tuple[int, int, int, int]) -> float:
        return (bb[0] + bb[2]) / 2.0

    # Sort by column then top-to-bottom within column.
    entries.sort(key=lambda e: (x_center(e[1]), e[1][1]))
    gap_threshold = max(100.0, float(board_w) * 0.055)
    columns: list[list[tuple[dict[str, Any], tuple[int, int, int, int]]]] = []
    for p, bb in entries:
        xc = x_center(bb)
        if not columns:
            columns.append([(p, bb)])
            continue
        ref_xc = x_center(columns[-1][0][1])
        if abs(xc - ref_xc) <= gap_threshold:
            columns[-1].append((p, bb))
        else:
            columns.append([(p, bb)])
    for col in columns:
        col.sort(key=lambda e: e[1][1])
    return [[pair[0] for pair in col] for col in columns]


def _pct_span(lo: int, hi: int, denom: int) -> str:
    if denom <= 0:
        return f"{lo}–{hi}px"
    a = int(round(100 * lo / denom))
    b = int(round(100 * hi / denom))
    return f"x≈{lo}–{hi}px ({a}%–{b}% of width)"


def _pct_y_span(lo: int, hi: int, denom: int) -> str:
    if denom <= 0:
        return f"{lo}–{hi}px"
    a = int(round(100 * lo / denom))
    b = int(round(100 * hi / denom))
    return f"y≈{lo}–{hi}px ({a}%–{b}% of height)"


def _feature_panel_grid_paragraph(
    panels: list[dict[str, Any]],
    *,
    board_w: int,
    board_h: int,
    centerpiece_x: tuple[int, int] | None,
) -> str:
    """Describe the twelve functional UI regions using catalog bboxes (prompt-only)."""
    if not panels:
        return ""

    columns = _cluster_panel_columns(panels, board_w)
    if not columns:
        return ""

    n_slots = sum(len(c) for c in columns)
    n_col = len(columns)
    row_counts = [len(c) for c in columns]
    row_hint = max(row_counts) if row_counts else 0

    parts: list[str] = [
        f" Functional UI panels ({n_slots} rectangular game-UI or card slots): "
        f"arrange as {n_col} vertical columns × up to {row_hint} stacked rows "
        f"between the perimeter track and the central illustration — "
        f"each slot its own clearly bounded rectangle (no merged murals across slots). ",
    ]

    if centerpiece_x is not None:
        cx1, cx2 = centerpiece_x
        parts.append(
            f"Reserve the horizontal centerpiece band x={cx1}–{cx2}px for central artwork only; "
            f"paint every functional panel entirely outside that band "
            f"(x < {cx1} or x > {cx2}), never spanning across it. "
        )

    col_chunks: list[str] = []
    for i, col in enumerate(columns):
        if not col:
            continue
        bbs = [_panel_bbox_tuple(p) for p in col]
        bbs = [b for b in bbs if b is not None]
        if not bbs:
            continue
        x1m = min(b[0] for b in bbs)
        x2m = max(b[2] for b in bbs)
        y1m = min(b[1] for b in bbs)
        y2m = max(b[3] for b in bbs)
        if n_col == 4 and i < 4:
            label = _FOUR_COL_LABELS[i]
        else:
            label = f"column {i + 1} from the left"
        col_chunks.append(
            f"{label}: {_pct_span(x1m, x2m, board_w)}, {_pct_y_span(y1m, y2m, board_h)}, "
            f"{len(col)} stacked slot(s)."
        )

    parts.append("Columns left→right: " + "; ".join(col_chunks) + ".")

    ts = None
    for p in panels:
        if not isinstance(p, dict):
            continue
        ts = p.get("target_size")
        if isinstance(ts, (list, tuple)) and len(ts) >= 2:
            try:
                tw, th = int(ts[0]), int(ts[1])
                if tw > 0 and th > 0:
                    parts.append(
                        f" Each panel slot is roughly card/UI-sized (~{tw}×{th}px target), "
                        f"similar footprint across slots."
                    )
                    break
            except (TypeError, ValueError):
                pass

    return "".join(parts)


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

    cp = catalog.get("centerpiece") or {}
    cp_bbox = cp.get("bbox") if isinstance(cp, dict) else None
    centerpiece_x_band: tuple[int, int] | None = None
    if isinstance(cp_bbox, (list, tuple)) and len(cp_bbox) >= 4:
        try:
            centerpiece_x_band = (int(cp_bbox[0]), int(cp_bbox[2]))
        except (TypeError, ValueError):
            centerpiece_x_band = None

    panel_list = panels if isinstance(panels, list) else []
    grid_para = _feature_panel_grid_paragraph(
        panel_list,
        board_w=w,
        board_h=h,
        centerpiece_x=centerpiece_x_band,
    )

    if grid_para:
        panel_hint = grid_para
    elif pl is not None and pr is not None and (pl + pr) > 0:
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

    centerpiece_hint = ""
    if isinstance(cp_bbox, (list, tuple)) and len(cp_bbox) >= 4:
        try:
            x1, y1, x2, y2 = int(cp_bbox[0]), int(cp_bbox[1]), int(cp_bbox[2]), int(cp_bbox[3])
            centerpiece_hint = (
                f" Reserve the central illustration block roughly "
                f"x={x1}–{x2}, y={y1}–{y2} on this {w}×{h} canvas "
                f"(perimeter tracks stay outside this band)."
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
        f"Composition: canvas about {w}×{h} px ({rw}:{rh} aspect). "
        f"Readable separation between perimeter ring, twelve inner UI slots, and centerpiece — "
        f"approximate geometry is fine; merged ambiguous blobs are not. "
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

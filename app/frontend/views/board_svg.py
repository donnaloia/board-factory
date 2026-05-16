"""Board SVG renderer — generates an interactive inline SVG from a catalog dict.

This module produces the SVG used by the live `/board` view. It shares layout
geometry with ``render_spec_svg`` (the board Tech spec page) but adds two things
the spec diagram does not:

1. Per-cell status color (pending / has-candidates / approved)
2. Click handlers wrapping each cell — perimeter cells link to /spaces, inner
   cells link to /panels/<id>, centerpiece links to /centerpiece

Approved cells render their actual approved PNG inside the SVG via
`<image href>`, so the board diagram doubles as a live composite preview.
"""

from __future__ import annotations

import html
from typing import Iterable

from domains.spaces.geometry import resolve_position
from domains.spaces.status import CellStatus


# ────────────────────────── SVG helpers ──────────────────────────


def _status_class(s: CellStatus) -> str:
    if s.approved:
        return "approved"
    if s.candidates > 0:
        return "has-candidates"
    return "pending"


def _route_for(category: str, asset_id: str) -> str:
    """Legacy fallback route for users with JS disabled."""
    if category == "centerpiece":
        return "/centerpiece"
    if category == "panels":
        return f"/panels/{asset_id}"
    return "/spaces"


# ────────────────────────── rendering ──────────────────────────


def _design_kind(design: dict) -> str:
    """Classify a design for tinting purposes when no approved image exists yet."""
    did = design["id"]
    prompt = design.get("prompt", "").upper()
    if did.startswith("battle"):
        return "battle"
    if did.startswith("corner"):
        return "corner"
    # Any explicit label-style design (banner)
    label_markers = ("DAMNATION", "FATE", "JAIL", "FAIL", "GO ", "JAIR", "CHEST", "ABAIL")
    if any(m in prompt for m in label_markers):
        return "banner"
    return "perimeter"


def _label_for(design: dict) -> str | None:
    """Short uppercase label for a banner-style perimeter cell, or None."""
    prompt = design.get("prompt", "").upper()
    for marker in ("GO DAMNATION", "JAIR ABAIL", "COMMUNITY CHEST",
                   "DAMNATION", "FATE", "JAIL", "FAIL", "BATTLE"):
        if marker in prompt:
            return marker
    return None


def render_board_svg(
    catalog: dict,
    space_status: dict[str, CellStatus],
    panel_status: dict[str, CellStatus],
    centerpiece_status: CellStatus,
    frame_overlay_url: str | None = None,
) -> str:
    """Return an inline SVG string ready to be embedded in HTML.

    The SVG is laid out in true canvas pixels (via viewBox) so the consumer
    can size it freely with CSS without affecting hit boxes or proportions.
    """
    cw, ch = catalog["board_size"]
    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {cw} {ch}" '
        f'class="bf-board" xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'preserveAspectRatio="xMidYMid meet">'
    )
    parts.append(f'<rect x="0" y="0" width="{cw}" height="{ch}" fill="#0d0e10"/>')

    # ─── perimeter cells ───
    layout = catalog["board_spaces"]["layout"]
    designs = catalog["board_spaces"]["designs"]

    for design in designs:
        status = space_status.get(design["id"])
        kind = _design_kind(design)
        label = _label_for(design)
        for ref in design["positions"]:
            x, y, w, h = resolve_position(layout, ref)
            parts.append(_cell_svg(
                category="spaces",
                asset_id=design["id"],
                x=x, y=y, w=w, h=h,
                kind=kind,
                label=label,
                status=status,
                position_ref=ref,
            ))

    # ─── functional UI cells ───
    for panel in catalog["feature_panels"]["panels"]:
        bx1, by1, bx2, by2 = panel["bbox"]
        status = panel_status.get(panel["id"])
        parts.append(_cell_svg(
            category="panels",
            asset_id=panel["id"],
            x=bx1, y=by1, w=bx2 - bx1, h=by2 - by1,
            kind="functional",
            label=panel["id"],
            status=status,
        ))
        # House frame overlay (if adopted) — placed AFTER the cell so it sits
        # on top, AND outside the <a> link so clicks still hit the cell, not
        # the overlay.
        if frame_overlay_url and status and status.approved:
            pw, ph = bx2 - bx1, by2 - by1
            parts.append(
                f'<image href="{frame_overlay_url}?w={pw}&h={ph}" '
                f'x="{bx1}" y="{by1}" width="{pw}" height="{ph}" '
                f'preserveAspectRatio="xMidYMid slice" '
                f'style="image-rendering: pixelated; pointer-events: none;"/>'
            )

    # ─── centerpiece ───
    cp = catalog["centerpiece"]
    bx1, by1, bx2, by2 = cp["bbox"]
    parts.append(_cell_svg(
        category="centerpiece",
        asset_id="centerpiece",
        x=bx1, y=by1, w=bx2 - bx1, h=by2 - by1,
        kind="centerpiece",
        label="centerpiece",
        status=centerpiece_status,
    ))

    parts.append("</svg>")
    return "".join(parts)


def _cell_svg(
    *,
    category: str,
    asset_id: str,
    x: int, y: int, w: int, h: int,
    kind: str,
    label: str | None,
    status: CellStatus | None,
    position_ref: str | None = None,
) -> str:
    """One clickable cell. May be a colored placeholder or an approved image."""
    href = _route_for(category, asset_id)
    status_class = _status_class(status) if status else "pending"
    safe_id = asset_id.replace('"', "")
    pos_attr = ""
    if position_ref is not None:
        pos_attr = f' data-position-ref="{html.escape(position_ref, quote=True)}"'

    # Build a tooltip describing what's known about the cell.
    tooltip_parts = [safe_id]
    if status:
        if status.approved:
            tooltip_parts.append("approved")
        elif status.candidates:
            tooltip_parts.append(f"{status.candidates} candidates pending review")
        else:
            tooltip_parts.append("not generated yet")
    tooltip = " · ".join(tooltip_parts)

    inner = []

    # If approved, render the actual approved image inside the cell rect.
    if status and status.approved and status.approved_url:
        inner.append(
            f'<image href="{status.approved_url}" x="{x}" y="{y}" '
            f'width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice" '
            f'style="image-rendering: pixelated;"/>'
        )
        inner.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'class="bf-cell-overlay" fill="transparent"/>'
        )
    else:
        # Placeholder rect, tinted by kind.
        inner.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'class="bf-cell bf-{kind}"/>'
        )
        if label:
            cx, cy = x + w / 2, y + h / 2 + 4
            font_size = max(10, min(18, w // 12))
            inner.append(
                f'<text x="{cx:.0f}" y="{cy:.0f}" class="bf-cell-label bf-label-{kind}" '
                f'text-anchor="middle" font-size="{font_size}">{label}</text>'
            )

    # Status indicator (small dot in corner) for non-pending cells.
    if status and (status.approved or status.candidates):
        dot_color = "#16a34a" if status.approved else "#fbbf24"
        dx, dy = x + w - 12, y + 12
        inner.append(
            f'<circle cx="{dx}" cy="{dy}" r="6" fill="{dot_color}" '
            f'stroke="#0d0e10" stroke-width="2"/>'
        )

    # Click is handled by JS in the side-panel module; xlink:href stays as a
    # progressive-enhancement fallback (works when JS is disabled or hasn't
    # loaded yet). The JS calls preventDefault() on its own.
    return (
        f'<a xlink:href="{href}" class="bf-cell-link bf-{status_class}" '
        f'data-asset-id="{safe_id}" data-category="{category}"{pos_attr} '
        f'role="button" tabindex="0">'
        f'<title>{tooltip}</title>'
        f'{"".join(inner)}'
        f'</a>'
    )


# ────────────────────────── spec variant ──────────────────────────


def render_spec_svg(catalog: dict) -> str:
    """Render a non-interactive labeled board diagram for the tech spec page.

    Differences vs. render_board_svg: no <a> wrappers, no status colors, no
    click affordance, and richer text labels — banner labels, panel ids+sizes,
    and the centerpiece block all spell out their data. Built from the same
    catalog so it can never disagree with the live board.
    """
    cw, ch = catalog["board_size"]
    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {cw} {ch}" '
        f'class="bf-spec-board" xmlns="http://www.w3.org/2000/svg" '
        f'preserveAspectRatio="xMidYMid meet">'
    )
    parts.append(f'<rect x="0" y="0" width="{cw}" height="{ch}" fill="#0d0e10"/>')

    layout = catalog["board_spaces"]["layout"]
    designs = catalog["board_spaces"]["designs"]

    for design in designs:
        kind = _design_kind(design)
        label = _label_for(design)
        for ref in design.get("positions", []):
            x, y, w, h = resolve_position(layout, ref)
            parts.append(_spec_cell(x, y, w, h, kind=kind, label=label, sublabel=design["id"]))

    for panel in catalog["feature_panels"]["panels"]:
        bx1, by1, bx2, by2 = panel["bbox"]
        w, h = bx2 - bx1, by2 - by1
        ts = panel.get("target_size", [w, h])
        parts.append(_spec_cell(
            bx1, by1, w, h,
            kind="functional",
            label=panel["id"],
            sublabel=f"{ts[0]} × {ts[1]}",
            label_size=14,
        ))

    cp = catalog["centerpiece"]
    bx1, by1, bx2, by2 = cp["bbox"]
    cw2, ch2 = bx2 - bx1, by2 - by1
    ts = cp["target_size"]
    parts.append(
        f'<rect x="{bx1}" y="{by1}" width="{cw2}" height="{ch2}" '
        f'class="bf-cell bf-centerpiece" stroke-width="3"/>'
    )
    cx, cy = bx1 + cw2 / 2, by1 + ch2 / 2
    parts.append(
        f'<text x="{cx:.0f}" y="{cy - 30:.0f}" text-anchor="middle" '
        f'font-size="24" fill="#fbbf24" font-weight="700" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">CENTERPIECE</text>'
    )
    parts.append(
        f'<text x="{cx:.0f}" y="{cy + 5:.0f}" text-anchor="middle" '
        f'font-size="18" fill="#e6e8ec" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">demon</text>'
    )
    parts.append(
        f'<text x="{cx:.0f}" y="{cy + 40:.0f}" text-anchor="middle" '
        f'font-size="13" fill="#8a8f99" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">{ts[0]} × {ts[1]} px</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


def _spec_cell(
    x: int, y: int, w: int, h: int, *,
    kind: str,
    label: str | None,
    sublabel: str | None = None,
    label_size: int | None = None,
) -> str:
    inner: list[str] = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="bf-cell bf-{kind}"/>'
    ]
    cx = x + w / 2
    if label:
        size = label_size or max(10, min(16, w // 11))
        ly = y + h / 2 + (size / 3 if not sublabel else -2)
        inner.append(
            f'<text x="{cx:.0f}" y="{ly:.0f}" text-anchor="middle" '
            f'class="bf-cell-label bf-label-{kind}" font-size="{size}">{label}</text>'
        )
    if sublabel:
        sl_size = max(9, min(12, w // 18))
        sy = y + h / 2 + sl_size + 4
        inner.append(
            f'<text x="{cx:.0f}" y="{sy:.0f}" text-anchor="middle" '
            f'class="bf-cell-sublabel" font-size="{sl_size}">{sublabel}</text>'
        )
    return "".join(inner)

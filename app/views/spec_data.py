"""Pure functions that derive the spec page's tables from a catalog dict.

The spec page is a *generated* document — every number on it comes from
the catalog row in the database (``board_games.body_json``). This module
turns the catalog into the structured rows the Jinja template iterates
over: design summary, pixel-density rollup, battle-tile table, and a few
high-level numbers for the header.

Keep this module side-effect free and dict-in-rows-out so it stays trivial
to test and the rendering layer stays dumb.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


# ────────────────────────── helpers ──────────────────────────


def _resolve_position(layout: dict, ref: str) -> tuple[int, int, int, int]:
    """Mirror BoardSpacesSpec.resolve_position for raw dicts. Returns (x, y, w, h)."""
    row_name, idx_str = ref.split(".")
    idx = int(idx_str)
    row = layout[row_name]
    size = row["size"]
    spacing = row.get("spacing") or (size[0] if row.get("axis", "x") == "x" else size[1])
    if row.get("axis", "x") == "x":
        x, y = row["start"][0] + idx * spacing, row["start"][1]
    else:
        x, y = row["start"][0], row["start"][1] + idx * spacing
    return (x, y, size[0], size[1])


def _design_kind(design: dict) -> str:
    """Mirrors board_svg._design_kind so spec + live board agree on classification."""
    did = design["id"]
    prompt = design.get("prompt", "").upper()
    if did.startswith("battle"):
        return "battle"
    if did.startswith("corner"):
        return "corner"
    label_markers = ("DAMNATION", "FATE", "JAIL", "FAIL", "GO ", "JAIR", "CHEST", "ABAIL")
    if any(m in prompt for m in label_markers):
        return "banner"
    return "perimeter"


def _row_for_ref(ref: str) -> str:
    return ref.split(".")[0]


def _edge_for_row(row_name: str) -> str:
    return {
        "top_row": "top",
        "bottom_row": "bottom",
        "left_col": "left",
        "right_col": "right",
    }.get(row_name, row_name)


# ────────────────────────── public API ──────────────────────────


def header_summary(catalog: dict) -> dict:
    """High-level numbers that appear in the doc header strip."""
    designs = catalog["board_spaces"]["designs"]
    panels = catalog["feature_panels"]["panels"]
    layout = catalog["board_spaces"]["layout"]

    perimeter_count = sum(len(d.get("positions", [])) for d in designs)
    battle_count = sum(
        len(d.get("positions", []))
        for d in designs
        if _design_kind(d) == "battle"
    )

    return {
        "version": catalog.get("spec_version", "0.5"),
        "board_size": catalog["board_size"],
        "aspect": "16:9",  # derived from board_size in the future if you ever change it
        "perimeter_count": perimeter_count,
        "battle_count": battle_count,
        "functional_count": len(panels),
        "centerpiece_count": 1,
        "design_count": len(designs),
        "layout_rows": list(layout.keys()),
    }


def pixel_density_rows(catalog: dict) -> list[dict]:
    """One row per (kind, dimensions) bucket. The catalog drives the entire table.

    Buckets are: perimeter / corner / banner / battle for board spaces (further
    subdivided by tile size, since top/bottom and side tiles have different
    dimensions), then functional cells, then centerpiece.
    """
    layout = catalog["board_spaces"]["layout"]
    designs = catalog["board_spaces"]["designs"]
    panels = catalog["feature_panels"]["panels"]
    cp = catalog["centerpiece"]

    # Group every position by (kind, size).
    buckets: dict[tuple[str, tuple[int, int]], int] = defaultdict(int)
    for design in designs:
        kind = _design_kind(design)
        for ref in design.get("positions", []):
            _, _, w, h = _resolve_position(layout, ref)
            buckets[(kind, (w, h))] += 1

    kind_order = {"perimeter": 0, "corner": 1, "banner": 2, "battle": 3}
    edge_label = {
        (160, 180): "top/bottom",
        (180, 144): "sides",
    }
    rows: list[dict] = []
    for (kind, (w, h)), count in sorted(
        buckets.items(),
        key=lambda kv: (kind_order.get(kv[0][0], 99), kv[0][1])
    ):
        suffix = edge_label.get((w, h))
        label_kind = {
            "perimeter": "Perimeter",
            "corner": "Corner",
            "banner": "Red banner",
            "battle": "Battle",
        }.get(kind, kind.title())
        label = f"{label_kind} ({suffix})" if suffix else label_kind
        rows.append({
            "label": label,
            "kind": kind,
            "size": (w, h),
            "size_str": f"{w} × {h}",
            "pixels": w * h,
            "pixels_str": f"{w * h:,}",
            "count": count,
        })

    # Functional cells. We bucket them by target_size so cells with different
    # target dimensions show up as separate rows (today they're all 260×240).
    panel_buckets: Counter[tuple[int, int]] = Counter()
    for p in panels:
        ts = tuple(p["target_size"])
        panel_buckets[ts] += 1
    for size, count in sorted(panel_buckets.items()):
        w, h = size
        rows.append({
            "label": "Functional UI cell",
            "kind": "functional",
            "size": (w, h),
            "size_str": f"{w} × {h}",
            "pixels": w * h,
            "pixels_str": f"{w * h:,}",
            "count": count,
        })

    # Centerpiece (always exactly one).
    cw, ch = cp["target_size"]
    rows.append({
        "label": "Centerpiece",
        "kind": "centerpiece",
        "size": (cw, ch),
        "size_str": f"{cw} × {ch}",
        "pixels": cw * ch,
        "pixels_str": f"{cw * ch:,}",
        "count": 1,
    })
    return rows


def design_table_rows(catalog: dict) -> list[dict]:
    """One row per design entry — the actual content of the catalog, in spec form."""
    layout = catalog["board_spaces"]["layout"]
    designs = catalog["board_spaces"]["designs"]
    rows: list[dict] = []
    for d in designs:
        positions = d.get("positions", [])
        sample_size = None
        if positions:
            _, _, w, h = _resolve_position(layout, positions[0])
            sample_size = (w, h)
        rows.append({
            "id": d["id"],
            "kind": _design_kind(d),
            "prompt": d.get("prompt", ""),
            "size_str": f"{sample_size[0]} × {sample_size[1]}" if sample_size else "—",
            "uses": len(positions),
            "positions": positions,
        })
    return rows


def panel_table_rows(catalog: dict) -> list[dict]:
    """Functional UI cells, one row each. bbox + size + prompt."""
    rows: list[dict] = []
    for p in catalog["feature_panels"]["panels"]:
        bbox = p["bbox"]
        ts = p["target_size"]
        rows.append({
            "id": p["id"],
            "bbox": bbox,
            "bbox_str": f"({bbox[0]}, {bbox[1]}) → ({bbox[2]}, {bbox[3]})",
            "size_str": f"{ts[0]} × {ts[1]}",
            "prompt": p.get("prompt", ""),
            "needs_active": p.get("needs_active", False),
            "active_kind": p.get("active_kind"),
        })
    return rows


def battle_table_rows(catalog: dict) -> list[dict]:
    """Subset of design positions where the design is classified as battle."""
    layout = catalog["board_spaces"]["layout"]
    rows: list[dict] = []
    for d in catalog["board_spaces"]["designs"]:
        if _design_kind(d) != "battle":
            continue
        for ref in d.get("positions", []):
            x, y, w, h = _resolve_position(layout, ref)
            rows.append({
                "ref": ref,
                "edge": _edge_for_row(_row_for_ref(ref)),
                "size_str": f"{w} × {h}",
                "coords": (x, y),
                "coords_str": f"({x}, {y})",
                "design_id": d["id"],
            })
    return rows


def design_summary_by_kind(catalog: dict) -> list[dict]:
    """For the legend: kind → count + sample size + sample prompt."""
    designs = catalog["board_spaces"]["designs"]
    layout = catalog["board_spaces"]["layout"]

    by_kind: dict[str, dict] = {}
    for d in designs:
        kind = _design_kind(d)
        positions = d.get("positions", [])
        if not positions:
            continue
        _, _, w, h = _resolve_position(layout, positions[0])
        bucket = by_kind.setdefault(kind, {
            "kind": kind,
            "designs": 0,
            "positions": 0,
            "sizes": set(),
            "sample_prompt": d.get("prompt", ""),
        })
        bucket["designs"] += 1
        bucket["positions"] += len(positions)
        bucket["sizes"].add((w, h))

    order = {"corner": 0, "banner": 1, "battle": 2, "perimeter": 3}
    out: list[dict] = []
    for kind in sorted(by_kind, key=lambda k: order.get(k, 99)):
        b = by_kind[kind]
        sizes = sorted(b["sizes"])
        size_str = " or ".join(f"{w} × {h}" for w, h in sizes)
        out.append({
            "kind": kind,
            "designs": b["designs"],
            "positions": b["positions"],
            "size_str": size_str,
            "sample_prompt": b["sample_prompt"],
        })
    return out

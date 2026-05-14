"""Layout math for catalog ``board_spaces.layout`` — shared by spec tables and SVG."""

from __future__ import annotations


def resolve_position(layout: dict, ref: str) -> tuple[int, int, int, int]:
    """Mirror ``BoardSpacesSpec.resolve_position`` for raw dicts. Returns ``(x, y, w, h)``."""
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

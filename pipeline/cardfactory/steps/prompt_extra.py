"""Shared prompt fragments for chrome + illustration — pixel discipline and palette."""

from __future__ import annotations

_MAX_SWATCHES_IN_PROMPT = 18


def format_palette_clause(colors: list[tuple[int, int, int]]) -> str:
    """Short line listing hex colours for the model (bounded length)."""
    if not colors:
        return ""
    parts: list[str] = []
    for r, g, b in colors[:_MAX_SWATCHES_IN_PROMPT]:
        parts.append(f"#{r:02x}{g:02x}{b:02x}")
    extra = len(colors) - _MAX_SWATCHES_IN_PROMPT
    suffix = f" (+{extra} more from same family)" if extra > 0 else ""
    return (
        " COLOUR DISCIPLINE — treat these as the primary swatches (flat fills, no "
        "rainbow drift outside this family): " + ", ".join(parts) + suffix + "."
    )

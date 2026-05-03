"""Fixed generation-role phrases prepended after ``catalog.style.prompt``.

These tune hierarchy (track vs event vs panel vs centerpiece) so perimeter tiles
stay legible and the center can carry more detail — defaults live in code, not
the database (see project discussion)."""

from __future__ import annotations

# Perimeter / board-track spaces (txt2img at design tile size).
_SPACE_STANDARD = (
    "Small top-down board game track space, legible when viewed from playing distance. "
    "One clear focal icon or prop only; quiet simple ground; strong readable silhouette; "
    "avoid dense texture or micro-detail that blends into neighboring cells. "
)

_SPACE_EVENT = (
    "Special event board game space: must read distinctly from ordinary track cells. "
    "One bold iconic focal; higher contrast and simpler field than property tiles; "
    "avoid matching the same busy density as surrounding spaces. "
)

_PANEL = (
    "Rectangular in-world game UI panel illustration for a board mockup. "
    "One main readable subject; calm uncluttered background suited to a card or UI tile frame; "
    "clear focal, no miniature clutter. "
)

_CENTERPIECE = (
    "Hero centerpiece illustration for this board: single dominant subject with the richest detail "
    "on the entire table; controlled atmospheric background that supports the subject without "
    "the same fine-grained noise as edge tiles; clear depth and focal hierarchy. "
)


def space_role_phrase(space_kind: str | None) -> str:
    """Return framing copy for a ``BoardSpaceDesign.space_kind``."""
    if space_kind == "event":
        return _SPACE_EVENT
    return _SPACE_STANDARD


def panel_role_phrase() -> str:
    """Framing for functional feature panels (img2img / inpaint)."""
    return _PANEL


def centerpiece_role_phrase() -> str:
    """Framing for the centerpiece (initial img2img and subsequent txt2img)."""
    return _CENTERPIECE


def compose_prompt(style_prefix: str, role_phrase: str, base: str) -> str:
    """Concatenate global style, role discipline, and user/catalog prompt text."""
    return f"{style_prefix}{role_phrase}{base}"

"""Tech-spec content loaded by the web app (markdown prose for spec pages)."""

from tech_spec.loader import (
    BOARD_LAYOUT_PROSE_PATH,
    load_board_layout_prose_sections,
    load_spec_prose_sections,
)

__all__ = [
    "BOARD_LAYOUT_PROSE_PATH",
    "load_board_layout_prose_sections",
    "load_spec_prose_sections",
]

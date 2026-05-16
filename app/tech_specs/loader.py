"""Read tech-spec markdown from disk for in-app pages."""

from __future__ import annotations

import os
from pathlib import Path

import markdown

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
TECH_SPEC_ROOT = REPO_ROOT / "tech-spec"
BOARD_LAYOUT_PROSE_PATH = TECH_SPEC_ROOT / "board-layout" / "prose.md"


def load_board_layout_prose_sections() -> dict[str, str]:
    """Parse ``tech-spec/board-layout/prose.md`` into HTML sections by ``##`` heading."""
    if not BOARD_LAYOUT_PROSE_PATH.is_file():
        return {}
    raw = BOARD_LAYOUT_PROSE_PATH.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is None:
            continue
        sections[current].append(line)
    return {
        slug: markdown.markdown("\n".join(body), extensions=["tables"])
        for slug, body in sections.items()
    }


def load_spec_prose_sections() -> dict[str, str]:
    """Alias for board layout prose (legacy name used by board routes)."""
    return load_board_layout_prose_sections()

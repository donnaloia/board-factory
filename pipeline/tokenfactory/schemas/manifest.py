"""Board Tokens pipeline — on-disk schema for design_lock.json and the
packed animation manifest.json.
"""

from __future__ import annotations

from pydantic import BaseModel


class FrameRect(BaseModel):
    """Location of one frame inside the atlas."""
    x: int
    y: int
    w: int
    h: int


class ClipEntry(BaseModel):
    """One animation clip as stored in the live manifest."""
    frames: list[FrameRect]
    fps: int = 12
    loop: bool = True
    #: When True the runtime may mirror horizontally for the opposite direction.
    flip_x: bool = False


class AnimationManifest(BaseModel):
    """Root of ``animations/live/manifest.json``."""
    token_slug: str
    run_id: str
    canvas_w: int
    canvas_h: int
    pivot_x: int
    pivot_y: int
    clips: dict[str, ClipEntry]
    #: Maps locomotion direction to a clip name.
    edge_kind_routing: dict[str, str] = {}
    created_ms: int


class DesignLock(BaseModel):
    """Root of ``design_lock.json`` (written when user commits canonical)."""
    slug: str
    display_name: str = ""
    locomotion_profile: str = "walk"
    facing_policy: str = "flip_x"
    canvas_w: int = 96
    canvas_h: int = 128
    pivot_x: int = 48
    pivot_y: int = 120
    frame_fps: int = 12
    #: Clip names to generate for this token.
    clips: list[str] = []
    #: Serialised TokenPalette (hex strings) computed via OKLch.
    token_palette: dict[str, list[str]] = {}
    #: One-line style description for AI prompts.
    style_sentence: str = ""

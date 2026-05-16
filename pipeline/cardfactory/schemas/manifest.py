"""Pydantic manifests for Card Factory pipeline artifacts.

Written to disk alongside generated PNGs so each asset is reproducible.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class InnerRect(BaseModel):
    """Pixel-space bounding box of the interior hull."""

    x: int
    y: int
    w: int
    h: int


class FrameCandidateManifest(BaseModel):
    """Written once per candidate inside ``frames/candidates/job_{id}/``."""

    deck_id: str
    job_id: str
    candidate_index: int
    canvas_w: int
    canvas_h: int
    inner_rect: InnerRect
    m_chrome_paint_hash: str
    provider: str
    model_id: str
    layout_template_id: str
    created_ms: int


class CardManifest(BaseModel):
    """Written alongside the live card PNG in ``cards/{slot_index}/live/``."""

    deck_id: str
    slot_index: int
    frame_commit_id: int
    layout_template_id: str
    canvas_w: int
    canvas_h: int
    inner_rect: InnerRect
    illustration_prompt_hash: str
    provider: str
    model_id: str
    created_ms: int
    notes: str = ""

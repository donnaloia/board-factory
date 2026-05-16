"""Per-job proposal manifest written to ``_proposals/<job_id>/manifest.json``.

Mirrors the frame-proposal manifest pattern in ``boardfactory`` (deliberate
duplication per the no-cross-pipeline-imports rule). Read by the app's
``manifest_io`` slice when serving the candidate gallery and again at commit
to look up the chosen file's metadata.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnimationParams(BaseModel):
    """Loop targets requested for the job (what the user asked for)."""

    fps: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    candidates: int = Field(gt=0)
    encoding: str
    loop_strategy: str
    animation_prompt: str = ""


class AnimationCandidate(BaseModel):
    """One produced candidate clip on disk."""

    index: int = Field(ge=0)
    filename: str
    encoding: str
    fps: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    frame_count: int = Field(gt=0)
    loop_strategy: str
    sha256: str
    seed: int | None = None
    notes: str = ""


class ProposalManifest(BaseModel):
    """Top-level manifest for one animate-space job."""

    job_id: str
    cell_id: str
    source_asset_version_id: int | None = None
    source_basename: str | None = None
    provider: str
    model_id: str
    params: AnimationParams
    candidates: list[AnimationCandidate]
    created_ms: int

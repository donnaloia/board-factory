"""The atomic animate-space operation.

Pipeline shape per call:

    1. Provider call (image-to-video), N candidate clips at the requested
       fps + duration.
    2. Apply the loop-closure strategy to each candidate (seamless / crossfade /
       pingpong / dissolve) so playback in an engine has no hard cut.
    3. Encode each candidate to GIF or APNG.
    4. Write candidate files + a single ``manifest.json`` into ``proposal_dir``.
    5. Return :class:`AnimateResult` with per-candidate hashes and realized cost.

The op is **path-aware but board-agnostic**: the caller (an app-side adapter)
hands it a fully-resolved ``proposal_dir`` and the source PNG bytes. The
pipeline never reads ``boardfactory.config`` or any board state.

Promotion (moving a candidate to ``live.<ext>``) and DB persistence are the
app's responsibility — see ``app/domains/spaces/animations/services.py``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import (
    ALLOWED_ENCODINGS,
    ALLOWED_LOOP_STRATEGIES,
)
from ..providers.base import I2VProvider
from ..schemas.manifest import (
    AnimationCandidate,
    AnimationParams,
    ProposalManifest,
)
from ..steps.encode import encode_clip, file_extension_for
from ..steps.loop_close import close_loop
from .progress import ProgressSink


@dataclass(frozen=True)
class AnimateSpec:
    """Everything ``animate_space`` needs to produce one job's worth of candidates.

    Built once by the app-side adapter; the pipeline op is mechanical from
    here on. Path validation lives in the adapter so the pipeline can stay
    ignorant of where things go on disk.
    """

    job_id: str
    cell_id: str
    source_png: bytes
    source_asset_version_id: int | None
    source_basename: str | None
    proposal_dir: Path
    fps: int
    duration_ms: int
    candidates: int
    encoding: str
    loop_strategy: str
    seed: int | None = None
    animation_prompt: str = ""


@dataclass(frozen=True)
class CandidateRecord:
    """One produced candidate, returned from the op for adapter logging."""

    index: int
    filename: str
    sha256: str
    frame_count: int
    encoding: str
    loop_strategy: str
    seed: int | None
    notes: str


@dataclass(frozen=True)
class AnimateResult:
    """Outcome of one animate-space job."""

    spec: AnimateSpec
    candidates: list[CandidateRecord]
    manifest_path: Path
    spent_usd: float


def animate_space(
    spec: AnimateSpec,
    provider: I2VProvider,
    sink: ProgressSink,
) -> AnimateResult:
    """Produce ``spec.candidates`` looping clips and a manifest in ``spec.proposal_dir``.

    Caller must guarantee ``proposal_dir`` is empty (or freshly created)
    before invocation; the op makes no attempt to merge with prior contents.
    """
    _validate_spec(spec)
    spec.proposal_dir.mkdir(parents=True, exist_ok=True)

    sink.start(f"animate cell:{spec.cell_id}", total=spec.candidates)
    sink.log(
        f"animate {spec.candidates}× clips "
        f"(fps={spec.fps}, duration_ms={spec.duration_ms}, "
        f"encoding={spec.encoding}, loop={spec.loop_strategy}, "
        f"provider={provider.name}/{provider.model_id})"
    )

    clips = provider.generate(
        spec.source_png,
        fps=spec.fps,
        duration_ms=spec.duration_ms,
        candidates=spec.candidates,
        seed=spec.seed,
        animation_prompt=spec.animation_prompt,
    )
    if not clips:
        sink.log("FAIL: provider returned no candidates")
        return AnimateResult(
            spec=spec,
            candidates=[],
            manifest_path=spec.proposal_dir / "manifest.json",
            spent_usd=0.0,
        )

    records: list[CandidateRecord] = []
    manifest_candidates: list[AnimationCandidate] = []
    ext = file_extension_for(spec.encoding)

    for i, clip in enumerate(clips):
        closed = close_loop(clip.frames, spec.loop_strategy)
        encoded = encode_clip(closed, fps=spec.fps, encoding=spec.encoding)
        filename = f"{i}.{ext}"
        out_path = spec.proposal_dir / filename
        out_path.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()

        records.append(
            CandidateRecord(
                index=i,
                filename=filename,
                sha256=digest,
                frame_count=len(closed),
                encoding=spec.encoding,
                loop_strategy=spec.loop_strategy,
                seed=clip.seed,
                notes=clip.notes,
            )
        )
        manifest_candidates.append(
            AnimationCandidate(
                index=i,
                filename=filename,
                encoding=spec.encoding,
                fps=spec.fps,
                duration_ms=spec.duration_ms,
                frame_count=len(closed),
                loop_strategy=spec.loop_strategy,
                sha256=digest,
                seed=clip.seed,
                notes=clip.notes,
            )
        )
        sink.step(filename)

    manifest = ProposalManifest(
        job_id=spec.job_id,
        cell_id=spec.cell_id,
        source_asset_version_id=spec.source_asset_version_id,
        source_basename=spec.source_basename,
        provider=provider.name,
        model_id=provider.model_id,
        params=AnimationParams(
            fps=spec.fps,
            duration_ms=spec.duration_ms,
            candidates=spec.candidates,
            encoding=spec.encoding,
            loop_strategy=spec.loop_strategy,
            animation_prompt=spec.animation_prompt or "",
        ),
        candidates=manifest_candidates,
        created_ms=int(time.time() * 1000),
    )
    manifest_path = spec.proposal_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2))

    spent_usd = float(
        provider.cost_estimate(candidates=len(clips), duration_ms=spec.duration_ms)
    )
    sink.log(f"wrote {len(records)} candidate(s) + manifest to {spec.proposal_dir.name}")

    return AnimateResult(
        spec=spec,
        candidates=records,
        manifest_path=manifest_path,
        spent_usd=spent_usd,
    )


def _validate_spec(spec: AnimateSpec) -> None:
    """Fail fast on invalid specs so the adapter sees a clear error.

    Per ``.cursorrules``: "No silent fallbacks for required state."
    """
    if not spec.source_png:
        raise ValueError("AnimateSpec.source_png must contain bytes")
    if spec.fps <= 0:
        raise ValueError(f"AnimateSpec.fps must be positive (got {spec.fps})")
    if spec.duration_ms <= 0:
        raise ValueError(f"AnimateSpec.duration_ms must be positive (got {spec.duration_ms})")
    if spec.candidates <= 0:
        raise ValueError(
            f"AnimateSpec.candidates must be positive (got {spec.candidates})"
        )
    if spec.encoding not in ALLOWED_ENCODINGS:
        raise ValueError(
            f"AnimateSpec.encoding {spec.encoding!r} not in {ALLOWED_ENCODINGS}"
        )
    if spec.loop_strategy not in ALLOWED_LOOP_STRATEGIES:
        raise ValueError(
            f"AnimateSpec.loop_strategy {spec.loop_strategy!r} not in {ALLOWED_LOOP_STRATEGIES}"
        )

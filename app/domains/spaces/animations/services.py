"""Service-layer orchestration for space animations.

Per ``.cursorrules`` "service shape": each service function reads as a short,
top-down chain of named function calls so the high-level flow is obvious at
a glance. Non-trivial work is factored into private helpers below.

Responsibilities:

  * :func:`assert_can_animate` — gate (kind, live static art) — fails fast.
  * :func:`enqueue_animation_job` — start a 3-candidate job.
  * :func:`list_proposals` — read the on-disk manifest for the candidate gallery.
  * :func:`commit_proposal` — promote one candidate, replace prior live, persist row.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass

from sqlalchemy import select

from infrastructure import board_store as bs
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from domains.spaces.models import CellRecord
from domains.spaces.animations import manifest_io, repository
from domains.spaces.animations.models import SpaceAnimationRecord


# ────────────────────────── exceptions ──────────────────────────


class AnimationGateError(RuntimeError):
    """Raised when ``assert_can_animate`` rejects a cell.

    Routes translate this into HTTP 4xx; tests assert the message.
    """


class ProposalNotFound(RuntimeError):
    """Raised when ``commit_proposal`` cannot locate the requested candidate."""


# ────────────────────────── views ──────────────────────────


@dataclass(frozen=True)
class ProposalCandidateView:
    index: int
    filename: str
    encoding: str
    fps: int
    duration_ms: int
    frame_count: int
    loop_strategy: str
    sha256: str
    notes: str


@dataclass(frozen=True)
class ProposalView:
    job_id: str
    cell_id: str
    provider: str
    model_id: str
    source_asset_version_id: int | None
    candidates: list[ProposalCandidateView]
    created_ms: int


# ────────────────────────── gate ──────────────────────────


# MVP allow-list: only ``functional`` cells may animate. See plan + spec §13.1.
_ALLOWED_KINDS = ("functional",)


def assert_can_animate(board_id: str, cell_id: str) -> CellRecord:
    """Return the cell row if it may animate; raise :class:`AnimationGateError` otherwise.

    Fails fast per ``.cursorrules`` "no silent fallbacks":

      * cell must exist on this board
      * cell.kind must be in the MVP allow-list (``functional``)
      * cell must have live static art (``live_asset_version_id IS NOT NULL``)
    """
    cell = _load_cell_or_die(board_id, cell_id)
    _assert_kind_allowed(cell)
    _assert_has_live_static(cell)
    return cell


def _load_cell_or_die(board_id: str, cell_id: str) -> CellRecord:
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        if cell is None or cell.board_uuid != board_id:
            raise AnimationGateError(
                f"Cell {cell_id!r} not found on board {board_id!r}."
            )
        session.expunge(cell)
        return cell


def _assert_kind_allowed(cell: CellRecord) -> None:
    if cell.kind not in _ALLOWED_KINDS:
        raise AnimationGateError(
            f"Cell kind {cell.kind!r} is not animatable in MVP "
            f"(allowed: {_ALLOWED_KINDS}). See tech-spec/space-animations/spec.md §13.1."
        )


def _assert_has_live_static(cell: CellRecord) -> None:
    if cell.live_asset_version_id is None:
        raise AnimationGateError(
            f"Cell {cell.id!r} has no live static art committed yet. "
            "Animation requires a live static asset (spec §G1)."
        )


# ────────────────────────── enqueue ──────────────────────────


def build_animation_job_label(cell: CellRecord) -> str:
    """Human-friendly job tray label."""
    return f"Animate · {cell.slug}"


def estimate_animation_cost_usd() -> float:
    """Forward-looking cost estimate used in the job tray + side panel UI.

    Asks the configured provider for the cost of one full job (N candidate
    clips at the configured duration). The mock provider returns 0; the
    OpenAI provider returns ``candidates × per-image-cost``.

    Lives at the service layer (not the route) so the cell side panel
    can also call it for its action-button "est" label.
    """
    from space_animations import config as anim_config
    from space_animations.providers.factory import select_provider

    name = anim_config.provider_name()
    if name == "mock":
        provider = select_provider(name)
    else:
        # We don't actually need the API key to ask for an estimate, but
        # the factory rightly refuses to instantiate the OpenAI provider
        # without one. Use a sentinel so estimate calls work even when
        # the user hasn't connected their key yet — the action button is
        # disabled in that state anyway.
        provider = select_provider(name, openai_api_key="estimate-only")
    return float(
        provider.cost_estimate(
            candidates=anim_config.candidates(),
            duration_ms=anim_config.target_duration_ms(),
        )
    )


# ────────────────────────── proposals (read) ──────────────────────────


def list_proposals(board_id: str, cell_id: str, job_id: str) -> ProposalView:
    """Return the proposal manifest for the candidate gallery.

    Raises :class:`ProposalNotFound` when the manifest is missing — the
    job either failed before writing it or the directory was already
    cleaned up.
    """
    manifest = manifest_io.read_manifest(board_id, cell_id, job_id)
    if manifest is None:
        raise ProposalNotFound(
            f"No proposal manifest at "
            f"{manifest_io.manifest_rel(cell_id, job_id)!r}"
        )
    return ProposalView(
        job_id=manifest.job_id,
        cell_id=manifest.cell_id,
        provider=manifest.provider,
        model_id=manifest.model_id,
        source_asset_version_id=manifest.source_asset_version_id,
        candidates=[
            ProposalCandidateView(
                index=c.index,
                filename=c.filename,
                encoding=c.encoding,
                fps=c.fps,
                duration_ms=c.duration_ms,
                frame_count=c.frame_count,
                loop_strategy=c.loop_strategy,
                sha256=c.sha256,
                notes=c.notes,
            )
            for c in manifest.candidates
        ],
        created_ms=manifest.created_ms,
    )


# ────────────────────────── commit ──────────────────────────


def commit_proposal(
    board_id: str,
    cell_id: str,
    job_id: str,
    proposal_index: int,
) -> SpaceAnimationRecord:
    """Promote one candidate to live and persist a row in ``space_animations``.

    Top-down chain (per .cursorrules service shape):

      1. assert_can_animate           — kind + live static gate, returns cell
      2. _load_proposal_or_die        — manifest + chosen candidate
      3. _delete_prior_live           — drop prior live row + on-disk file
                                        (no archive: archives are untracked
                                        bytes and create orphans)
      4. _promote_proposal_file       — copy chosen candidate to live.<ext>
      5. _insert_committed_row        — DB row in space_animations
      6. _set_cell_live_pointer       — cells.live_animation_id = new row id
    """
    cell = assert_can_animate(board_id, cell_id)
    manifest, chosen = _load_proposal_or_die(board_id, cell_id, job_id, proposal_index)
    prev_animation_id = cell.live_animation_id
    if prev_animation_id is not None:
        repository.delete_committed_animation(prev_animation_id)
    _ensure_no_stray_live_file(board_id, cell_id)
    live_target = _promote_proposal_file(board_id, cell_id, job_id, chosen.filename, chosen.encoding)
    record = _insert_committed_row(
        cell=cell,
        chosen=chosen,
        manifest=manifest,
        live_rel_path=manifest_io.live_rel(cell_id, chosen.encoding),
        live_basename=live_target.name,
        proposal_manifest_rel_path=manifest_io.manifest_rel(cell_id, job_id),
    )
    _set_cell_live_pointer(cell_id, record.id)
    return record


def _load_proposal_or_die(
    board_id: str,
    cell_id: str,
    job_id: str,
    proposal_index: int,
):
    manifest = manifest_io.read_manifest(board_id, cell_id, job_id)
    if manifest is None:
        raise ProposalNotFound(
            f"No proposal manifest for job {job_id!r} on cell {cell_id!r}."
        )
    chosen = next((c for c in manifest.candidates if c.index == proposal_index), None)
    if chosen is None:
        raise ProposalNotFound(
            f"Proposal index {proposal_index} not in manifest "
            f"(have {[c.index for c in manifest.candidates]})."
        )
    src = manifest_io.proposal_file(board_id, cell_id, job_id, chosen.filename)
    if not src.exists():
        raise ProposalNotFound(
            f"Proposal file {src} listed in manifest is missing on disk."
        )
    return manifest, chosen


def _ensure_no_stray_live_file(board_id: str, cell_id: str) -> None:
    """Defensive: drop any leftover live.{gif,apng} for this cell.

    ``repository.delete_committed_animation`` already unlinks the file at
    its row's ``rel_path``. This sweep covers the rare case where a file
    exists on disk without a matching DB row (e.g. a previous crash mid-
    commit), which would otherwise silently shadow the new live promotion.
    """
    store = bs.get_store()
    for ext in ("gif", "apng"):
        rel = f"workspace/animations/{cell_id}/live.{ext}"
        if store.exists(board_id, rel):
            store.delete(board_id, rel)


def _promote_proposal_file(
    board_id: str,
    cell_id: str,
    job_id: str,
    filename: str,
    encoding: str,
):
    src = manifest_io.proposal_file(board_id, cell_id, job_id, filename)
    dst = manifest_io.live_path(board_id, cell_id, encoding)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _insert_committed_row(
    *,
    cell: CellRecord,
    chosen,
    manifest,
    live_rel_path: str,
    live_basename: str,
    proposal_manifest_rel_path: str,
) -> SpaceAnimationRecord:
    return repository.insert_committed_animation(
        board_uuid=cell.board_uuid,
        cell_id=cell.id,
        source_asset_version_id=manifest.source_asset_version_id,
        rel_path=live_rel_path,
        basename=live_basename,
        encoding=chosen.encoding,
        fps=chosen.fps,
        duration_ms=chosen.duration_ms,
        frame_count=chosen.frame_count,
        provider=manifest.provider,
        model_id=manifest.model_id,
        loop_strategy=chosen.loop_strategy,
        sha256=chosen.sha256,
        proposal_manifest_rel_path=proposal_manifest_rel_path,
        proposal_index=chosen.index,
        created_ms=int(time.time() * 1000),
        notes=chosen.notes,
    )


def _set_cell_live_pointer(cell_id: str, animation_id: int) -> None:
    if not repository.set_cell_live_animation(cell_id, animation_id):
        raise RuntimeError(
            f"Cell {cell_id!r} disappeared between gate check and commit; "
            "refusing to leave a dangling space_animations row."
        )


# ────────────────────────── side-panel payload helpers ──────────────────────────


def live_animation_payload(board_id: str, cell_id: str, http_prefix: str) -> dict | None:
    """Return a JSON-shaped dict describing the cell's live animation, or ``None``.

    Used by the cell side panel to decide whether to render the animation
    preview affordance and where to fetch the file from.
    """
    record = repository.get_live_for_cell(cell_id)
    if record is None:
        return None
    if not fs_ws.workspace_dir(board_id).exists():
        return None
    return {
        "id": record.id,
        "encoding": record.encoding,
        "fps": record.fps,
        "duration_ms": record.duration_ms,
        "frame_count": record.frame_count,
        "loop_strategy": record.loop_strategy,
        "provider": record.provider,
        "model_id": record.model_id,
        "url": f"{http_prefix}/api/cell-animation/{cell_id}/live",
        "created_ms": record.created_ms,
    }


def find_cell_id(board_id: str, category: str, asset_id: str) -> str | None:
    """Resolve URL-style ``(category, asset_id)`` to ``cells.id`` for this board."""
    from domains.spaces.repository import category_to_kind

    kind = category_to_kind(category)
    if kind is None:
        return None
    with session_scope() as session:
        return session.scalar(
            select(CellRecord.id).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == asset_id,
            )
        )

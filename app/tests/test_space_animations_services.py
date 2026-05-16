"""Service-layer tests for the space-animations slice.

Covers the gate (kind + live static art), the disk-side proposal manifest
plumbing, and the commit chain end-to-end against the on-disk mock provider.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from domains.spaces.assets.models import AssetVersionRecord
from domains.spaces.models import CellRecord


# ────────────────────────── helpers ──────────────────────────


def _write_live_png(board_id: str, category: str, asset_id: str, color=(80, 60, 40)) -> Path:
    path = fs_ws.live_path(board_id, category, asset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (*color, 255)).save(path)
    return path


def _seed_live_static(board_id: str, kind: str, slug: str, *, color=(60, 80, 40)) -> str:
    """Promote a live static PNG for a cell + insert the matching asset_versions row.

    Returns the cell id. Mirrors what the boardfactory ``live_promote`` event
    does in production; keeping it inline so animation tests do not need to
    spin up the full image pipeline.
    """
    category = {"perimeter": "spaces", "functional": "panels", "centerpiece": "centerpiece"}[kind]
    _write_live_png(board_id, category, slug, color=color)
    with session_scope() as session:
        cell = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )
        assert cell is not None, f"seeded board missing {kind}/{slug}"
        av = AssetVersionRecord(
            board_uuid=board_id,
            cell_id=cell.id,
            category=category,
            asset_id=slug,
            basename="seed.png",
            rel_path=f"history/{category}/{slug}/seed.png",
            sha256=None,
            ts_ms=int(time.time() * 1000),
            meta_json=None,
        )
        session.add(av)
        session.flush()
        cell.live_asset_version_id = av.id
        return cell.id


def _write_proposal_manifest(
    board_id: str,
    cell_id: str,
    job_id: str,
    *,
    candidate_count: int = 3,
    encoding: str = "gif",
) -> None:
    """Drop a fake-but-valid proposal directory + manifest on disk.

    Used by service-layer tests that exercise the commit chain without
    going through the worker (the worker is covered separately in the
    routes test).
    """
    from space_animations.providers.mock import MockI2VProvider
    from space_animations.ops.animate_space import AnimateSpec, animate_space
    from space_animations.ops.progress import NoopSink

    from domains.spaces.animations import manifest_io

    proposal_dir = manifest_io.proposal_dir(board_id, cell_id, job_id)
    src = Image.new("RGBA", (32, 32), (200, 100, 100, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    spec = AnimateSpec(
        job_id=job_id,
        cell_id=cell_id,
        source_png=buf.getvalue(),
        source_asset_version_id=None,
        source_basename="seed.png",
        proposal_dir=proposal_dir,
        fps=10,
        duration_ms=500,
        candidates=candidate_count,
        encoding=encoding,
        loop_strategy="crossfade",
    )
    animate_space(spec, MockI2VProvider(), NoopSink())


# ────────────────────────── gate ──────────────────────────


def test_gate_rejects_perimeter_kind(seeded_board):
    from domains.spaces.animations import services
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(seeded_board.id, "spaces", "corner_tl")
    assert cell_id

    with pytest.raises(services.AnimationGateError, match="not animatable"):
        services.assert_can_animate(seeded_board.id, cell_id)


def test_gate_rejects_functional_without_live_static(seeded_board):
    from domains.spaces.animations import services
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(seeded_board.id, "panels", "panel_left_top")
    assert cell_id

    with pytest.raises(services.AnimationGateError, match="live static"):
        services.assert_can_animate(seeded_board.id, cell_id)


def test_gate_accepts_functional_with_live_static(seeded_board):
    from domains.spaces.animations import services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    cell = services.assert_can_animate(seeded_board.id, cell_id)
    assert cell.id == cell_id
    assert cell.kind == "functional"


def test_gate_rejects_unknown_cell(seeded_board):
    from domains.spaces.animations import services

    with pytest.raises(services.AnimationGateError, match="not found"):
        services.assert_can_animate(seeded_board.id, "00000000-0000-0000-0000-000000000000")


# ────────────────────────── proposal listing ──────────────────────────


def test_list_proposals_returns_candidate_view(seeded_board):
    from domains.spaces.animations import services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    _write_proposal_manifest(seeded_board.id, cell_id, "job-abc")

    view = services.list_proposals(seeded_board.id, cell_id, "job-abc")
    assert view.job_id == "job-abc"
    assert view.cell_id == cell_id
    assert view.provider == "mock"
    assert len(view.candidates) == 3
    assert {c.index for c in view.candidates} == {0, 1, 2}
    for c in view.candidates:
        assert c.encoding == "gif"
        assert c.fps == 10


def test_list_proposals_missing_raises(seeded_board):
    from domains.spaces.animations import services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    with pytest.raises(services.ProposalNotFound):
        services.list_proposals(seeded_board.id, cell_id, "no-such-job")


# ────────────────────────── commit ──────────────────────────


def test_commit_promotes_file_and_writes_row(seeded_board):
    from domains.spaces.animations import manifest_io, repository, services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    _write_proposal_manifest(seeded_board.id, cell_id, "job-1")

    record = services.commit_proposal(seeded_board.id, cell_id, "job-1", proposal_index=1)

    assert record.id is not None
    assert record.cell_id == cell_id
    assert record.proposal_index == 1
    assert record.encoding == "gif"
    assert record.fps == 10

    live = manifest_io.live_path(seeded_board.id, cell_id, record.encoding)
    assert live.exists(), "commit must promote the chosen file to live"
    assert live.read_bytes().startswith(b"GIF8")

    fetched = repository.get_live_for_cell(cell_id)
    assert fetched is not None
    assert fetched.id == record.id


def test_delete_committed_animation_unlinks_file(seeded_board):
    """``repository.delete_committed_animation`` must remove the row's
    on-disk ``rel_path`` so the DB and disk stay in lock-step.
    """
    from infrastructure import board_store as bs
    from domains.spaces.animations import manifest_io, repository, services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    _write_proposal_manifest(seeded_board.id, cell_id, "job-x")
    record = services.commit_proposal(seeded_board.id, cell_id, "job-x", proposal_index=0)

    live = manifest_io.live_path(seeded_board.id, cell_id, record.encoding)
    assert live.exists()
    assert bs.get_store().exists(seeded_board.id, record.rel_path)

    repository.delete_committed_animation(record.id)

    assert repository.get_by_id(record.id) is None
    assert not bs.get_store().exists(seeded_board.id, record.rel_path)


def test_commit_replaces_prior_live_without_archiving(seeded_board):
    """Replacing a live clip must leave **no** untracked bytes behind.

    Earlier behaviour archived the prior live file under
    ``workspace/animations/<cell>/history/`` — those archives had no DB
    pointer and silently accumulated. The new contract: replacing a
    committed animation deletes the prior file via
    ``delete_committed_animation``; only the new ``live.<ext>`` exists.
    """
    from domains.spaces.animations import manifest_io, services
    from domains.spaces.animations import repository

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    _write_proposal_manifest(seeded_board.id, cell_id, "job-first")
    first = services.commit_proposal(seeded_board.id, cell_id, "job-first", proposal_index=0)

    _write_proposal_manifest(seeded_board.id, cell_id, "job-second")
    second = services.commit_proposal(seeded_board.id, cell_id, "job-second", proposal_index=2)

    history_dir = manifest_io.history_dir(seeded_board.id, cell_id)
    assert not history_dir.exists() or list(history_dir.iterdir()) == []

    live = manifest_io.live_path(seeded_board.id, cell_id, second.encoding)
    assert live.exists()
    assert repository.get_by_id(first.id) is None


def test_commit_rejects_unknown_index(seeded_board):
    from domains.spaces.animations import services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    _write_proposal_manifest(seeded_board.id, cell_id, "job-x")

    with pytest.raises(services.ProposalNotFound, match="index 99"):
        services.commit_proposal(seeded_board.id, cell_id, "job-x", proposal_index=99)


def test_commit_rejects_perimeter_cell(seeded_board):
    from domains.spaces.animations import services
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(seeded_board.id, "spaces", "corner_tl")
    assert cell_id
    _write_proposal_manifest(seeded_board.id, cell_id, "job-bad")

    with pytest.raises(services.AnimationGateError):
        services.commit_proposal(seeded_board.id, cell_id, "job-bad", proposal_index=0)

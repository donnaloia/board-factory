"""HTTP + worker tests for the space-animations slice.

Covers the route surface (gate, proposal listing, commit, file serving) plus
a direct invocation of the worker function so we exercise the full
manifest+candidates write path with the mock provider without depending on
the asyncio JobRunner inside a sync TestClient.
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from starlette.testclient import TestClient

from auth import services as auth_services
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from server import app
from domains.spaces.assets.models import AssetVersionRecord
from domains.spaces.models import CellRecord


# ────────────────────────── helpers ──────────────────────────


def _client() -> TestClient:
    return TestClient(app)


def _auth_cookie(test_user) -> dict:
    sid = auth_services.create_session_cookie(test_user.id)
    return {auth_services.COOKIE_NAME: sid}


def _seed_live_static(board_id: str, kind: str, slug: str, *, color=(60, 80, 40)) -> str:
    """Promote a live PNG + insert the matching asset_versions row + set FK."""
    category = {"perimeter": "spaces", "functional": "panels", "centerpiece": "centerpiece"}[kind]
    p = fs_ws.live_path(board_id, category, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (*color, 255)).save(p)
    with session_scope() as session:
        cell = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )
        assert cell is not None
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


def _write_proposal(
    board_id: str,
    cell_id: str,
    job_id: str,
    *,
    encoding: str = "gif",
) -> Path:
    """Run the pipeline op directly to get a real manifest + candidates on disk."""
    from space_animations.ops.animate_space import AnimateSpec, animate_space
    from space_animations.ops.progress import NoopSink
    from space_animations.providers.mock import MockI2VProvider

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
        duration_ms=400,
        candidates=3,
        encoding=encoding,
        loop_strategy="crossfade",
    )
    animate_space(spec, MockI2VProvider(), NoopSink())
    return proposal_dir


# ────────────────────────── animate (gate) ──────────────────────────


def test_animate_rejects_perimeter(seeded_board, test_user):
    bid = seeded_board.id
    path = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/spaces/corner_tl/animate"
    )
    r = _client().post(
        path,
        json={"animation_prompt": "Subtle pulsing glow."},
        cookies=_auth_cookie(test_user),
    )
    assert r.status_code == 400, r.text
    assert "not animatable" in r.text


def test_animate_rejects_functional_without_live_static(seeded_board, test_user):
    bid = seeded_board.id
    path = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/panels/panel_left_top/animate"
    )
    r = _client().post(
        path,
        json={"animation_prompt": "Gentle drift and shimmer."},
        cookies=_auth_cookie(test_user),
    )
    assert r.status_code == 400, r.text
    assert "live static" in r.text


def test_animate_returns_job_id_when_allowed(seeded_board, test_user):
    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    path = (
        f"/users/{test_user.username}/board-games/{seeded_board.id}"
        f"/api/cell/panels/panel_left_top/animate"
    )
    r = _client().post(
        path,
        json={"animation_prompt": "Soft glow on the focal element."},
        cookies=_auth_cookie(test_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "job_id" in body
    assert isinstance(body["job_id"], str)
    assert body["job_id"]


def test_animate_rejects_empty_or_missing_prompt(seeded_board, test_user):
    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    path = (
        f"/users/{test_user.username}/board-games/{seeded_board.id}"
        f"/api/cell/panels/panel_left_top/animate"
    )
    r = _client().post(path, cookies=_auth_cookie(test_user))
    assert r.status_code == 400
    assert "prompt" in r.json().get("detail", "").lower()

    r2 = _client().post(
        path, json={"animation_prompt": "   "}, cookies=_auth_cookie(test_user)
    )
    assert r2.status_code == 400
    assert "prompt" in r2.json().get("detail", "").lower()


# ────────────────────────── proposal listing ──────────────────────────


def test_list_proposals_endpoint(seeded_board, test_user):
    bid = seeded_board.id
    cell_id = _seed_live_static(bid, "functional", "panel_left_top")
    _write_proposal(bid, cell_id, "job-list")

    path = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/panels/panel_left_top/animations/proposals/job-list"
    )
    r = _client().get(path, cookies=_auth_cookie(test_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == "job-list"
    assert body["provider"] == "mock"
    assert len(body["candidates"]) == 3
    for c in body["candidates"]:
        assert c["url"].endswith(c["filename"])
        assert c["encoding"] == "gif"


def test_list_proposals_404_when_missing(seeded_board, test_user):
    bid = seeded_board.id
    _seed_live_static(bid, "functional", "panel_left_top")
    path = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/panels/panel_left_top/animations/proposals/no-such"
    )
    r = _client().get(path, cookies=_auth_cookie(test_user))
    assert r.status_code == 404


# ────────────────────────── commit + serve live ──────────────────────────


def test_commit_then_serve_live_round_trip(seeded_board, test_user):
    bid = seeded_board.id
    cell_id = _seed_live_static(bid, "functional", "panel_left_top")
    _write_proposal(bid, cell_id, "job-commit")

    base = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/panels/panel_left_top"
    )
    commit_url = f"{base}/animations/proposals/job-commit/commit"
    r = _client().post(
        commit_url,
        json={"proposal_index": 1},
        cookies=_auth_cookie(test_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cell_id"] == cell_id
    assert body["encoding"] == "gif"
    assert body["fps"] == 10
    assert body["url"].endswith("/live")

    # Live metadata endpoint reflects the commit.
    meta = _client().get(f"{base}/animations/live", cookies=_auth_cookie(test_user))
    assert meta.status_code == 200, meta.text
    live = meta.json()["live"]
    assert live is not None
    assert live["id"] == body["id"]

    # File serving endpoint streams the GIF bytes.
    serve = _client().get(
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell-animation/{cell_id}/live",
        cookies=_auth_cookie(test_user),
    )
    assert serve.status_code == 200, serve.text
    assert serve.headers["content-type"].startswith("image/gif")
    assert serve.content.startswith(b"GIF8")

    # Cell row carries the new live_animation_id FK.
    with session_scope() as session:
        cell = session.get(CellRecord, cell_id)
        assert cell is not None
        assert cell.live_animation_id == body["id"]


def test_commit_rejects_unknown_index(seeded_board, test_user):
    bid = seeded_board.id
    cell_id = _seed_live_static(bid, "functional", "panel_left_top")
    _write_proposal(bid, cell_id, "job-bad")
    url = (
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell/panels/panel_left_top/animations/proposals/job-bad/commit"
    )
    r = _client().post(
        url, json={"proposal_index": 17}, cookies=_auth_cookie(test_user)
    )
    assert r.status_code == 404, r.text


def test_serve_proposal_file(seeded_board, test_user):
    bid = seeded_board.id
    cell_id = _seed_live_static(bid, "functional", "panel_left_top")
    _write_proposal(bid, cell_id, "job-serve")
    r = _client().get(
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell-animation/{cell_id}/proposals/job-serve/0.gif",
        cookies=_auth_cookie(test_user),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/gif")
    assert r.content.startswith(b"GIF8")


def test_serve_proposal_file_traversal_rejected(seeded_board, test_user):
    bid = seeded_board.id
    cell_id = _seed_live_static(bid, "functional", "panel_left_top")
    r = _client().get(
        f"/users/{test_user.username}/board-games/{bid}"
        f"/api/cell-animation/{cell_id}/proposals/job-x/..%2Fmanifest.json",
        cookies=_auth_cookie(test_user),
    )
    # FastAPI normalizes the percent-encoded slash; either way nothing
    # outside the proposal dir should be reachable.
    assert r.status_code in (400, 404)


# ────────────────────────── worker (direct call) ──────────────────────────


def test_worker_writes_manifest_and_three_candidates(seeded_board):
    """Exercise the JobRunner adapter by calling it as a plain function."""
    from jobs.runner import Job
    from domains.spaces.animations import pipeline_jobs as adapters
    from boardfactory import config as bf_config
    from domains.spaces.animations import manifest_io

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    job = Job(id="worker-1", label="t", operation="animate.space", target="panel_left_top")
    cancel = threading.Event()

    with bf_config.scope_board(seeded_board.id):
        spent = adapters.animate_space_job(
            job, cancel,
            board_id=seeded_board.id,
            cell_id=cell_id,
            animation_prompt="Loop with gentle vertical float.",
        )

    # Mock provider is free.
    assert spent == 0.0

    proposal_dir = manifest_io.proposal_dir(seeded_board.id, cell_id, "worker-1")
    assert (proposal_dir / "manifest.json").is_file()
    gifs = sorted(proposal_dir.glob("*.gif"))
    assert len(gifs) == 3
    for gif in gifs:
        assert gif.read_bytes().startswith(b"GIF8")


def test_worker_fails_fast_without_live_static(seeded_board):
    from jobs.runner import Job
    from domains.spaces.animations import pipeline_jobs as adapters
    from boardfactory import config as bf_config
    from domains.spaces import repository as spaces_repo

    cell_id = spaces_repo.find_id(seeded_board.id, "panels", "panel_left_top")
    assert cell_id
    job = Job(id="worker-2", label="t", operation="animate.space", target="panel_left_top")

    with bf_config.scope_board(seeded_board.id):
        with pytest.raises(RuntimeError, match="live_asset_version_id"):
            adapters.animate_space_job(
                job, threading.Event(),
                board_id=seeded_board.id,
                cell_id=cell_id,
                animation_prompt="Any motion for adapter smoke test.",
            )

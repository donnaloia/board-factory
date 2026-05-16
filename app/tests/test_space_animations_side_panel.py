"""Side-panel payload tests for the space-animations slice.

The cell side panel (``side-panel.js``) decides whether to show the
"Animate" action and the live-loop preview based on the ``animation``
block returned by ``GET /api/cell/...``. These tests pin that contract.
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


def _write_live_png(board_id: str, category: str, asset_id: str) -> Path:
    p = fs_ws.live_path(board_id, category, asset_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (90, 60, 40, 255)).save(p)
    return p


def _seed_live_static(board_id: str, kind: str, slug: str) -> str:
    category = {"perimeter": "spaces", "functional": "panels", "centerpiece": "centerpiece"}[kind]
    _write_live_png(board_id, category, slug)
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


# ────────────────────────── animation block ──────────────────────────


def test_perimeter_payload_marks_animation_unsupported(seeded_board):
    """Perimeter cells can never animate in MVP — block must say ``supported: False``."""
    from domains.spaces import services as spaces_services

    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "spaces", "corner_tl"
    )
    a = payload["animation"]
    assert a is not None
    assert a["supported"] is False
    assert a["live"] is None
    assert a["animate_endpoint"] is None


def test_functional_payload_supports_but_blocks_without_live_static(seeded_board):
    """A functional cell with no live PNG is supported but action button must
    surface the blocker so the user sees why it's disabled."""
    from domains.spaces import services as spaces_services

    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    a = payload["animation"]
    assert a["supported"] is True
    assert a["has_live_static"] is False
    assert a["live"] is None
    assert a["animate_endpoint"] is not None
    assert a["animate_endpoint"].endswith("/api/cell/panels/panel_left_top/animate")


def test_functional_payload_with_live_static_exposes_endpoints(seeded_board):
    from domains.spaces import services as spaces_services

    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    a = payload["animation"]
    assert a["supported"] is True
    assert a["has_live_static"] is True
    assert "{job_id}" in a["proposals_url_template"]
    assert "{job_id}" in a["commit_url_template"]
    assert a["candidates"] >= 1
    assert a["fps"] >= 1
    assert a["duration_ms"] >= 100


def test_provider_ready_true_when_provider_is_mock(seeded_board):
    """Tests pin SPACE_ANIMATIONS_PROVIDER=mock — provider_ready must be True
    even though no OpenAI key is connected."""
    from domains.spaces import services as spaces_services

    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    a = payload["animation"]
    assert a["provider"] == "mock"
    assert a["provider_ready"] is True


def test_provider_ready_false_when_openai_default_no_key(monkeypatch, seeded_board):
    """Flipping back to the runtime default (openai) without a connected
    key must report provider_ready=False so the UI can surface a blocker."""
    monkeypatch.setenv("SPACE_ANIMATIONS_PROVIDER", "openai")
    from domains.spaces import services as spaces_services

    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    a = payload["animation"]
    assert a["provider"] == "openai"
    assert a["provider_ready"] is False
    assert a["openai_connected"] is False


def test_estimate_zero_for_mock_nonzero_for_openai(monkeypatch, seeded_board):
    from domains.spaces import services as spaces_services

    _seed_live_static(seeded_board.id, "functional", "panel_left_top")
    mock_payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    assert mock_payload["animation"]["estimate_usd"] == pytest.approx(0.0)

    monkeypatch.setenv("SPACE_ANIMATIONS_PROVIDER", "openai")
    openai_payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    # Estimate is candidates × per-image cost; specific value may evolve.
    assert openai_payload["animation"]["estimate_usd"] > 0


def test_live_animation_appears_in_payload_after_commit(seeded_board):
    from domains.spaces import services as spaces_services
    from domains.spaces.animations import services

    cell_id = _seed_live_static(seeded_board.id, "functional", "panel_left_top")

    # Drop a manifest + candidate files on disk via the pipeline op (mock).
    from space_animations.providers.mock import MockI2VProvider
    from space_animations.ops.animate_space import AnimateSpec, animate_space
    from space_animations.ops.progress import NoopSink
    from domains.spaces.animations import manifest_io

    proposal_dir = manifest_io.proposal_dir(seeded_board.id, cell_id, "job-payload")
    src = Image.new("RGBA", (32, 32), (50, 60, 70, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    spec = AnimateSpec(
        job_id="job-payload",
        cell_id=cell_id,
        source_png=buf.getvalue(),
        source_asset_version_id=None,
        source_basename="seed.png",
        proposal_dir=proposal_dir,
        fps=10,
        duration_ms=300,
        candidates=3,
        encoding="gif",
        loop_strategy="crossfade",
    )
    animate_space(spec, MockI2VProvider(), NoopSink())
    services.commit_proposal(seeded_board.id, cell_id, "job-payload", proposal_index=0)

    payload = spaces_services.build_cell_side_panel_payload(
        seeded_board.id, "panels", "panel_left_top"
    )
    live = payload["animation"]["live"]
    assert live is not None
    assert live["encoding"] == "gif"
    assert live["fps"] == 10
    assert live["url"].endswith(f"/api/cell-animation/{cell_id}/live")

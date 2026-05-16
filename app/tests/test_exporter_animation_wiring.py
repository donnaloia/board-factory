"""Tests for ``stage_animation_wiring`` — committed clips in project bundles."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from boardfactory.boards import default_catalog_dict

from domains.spaces.animations import manifest_io, repository as anim_repo, services as anim_services
from domains.boards.exporter.orchestrate import EXPORT_STAGES, run_board_export
from domains.boards.exporter.state import BoardExportOptions
from space_animations.ops.animate_space import AnimateSpec, animate_space
from space_animations.ops.progress import NoopSink
from space_animations.providers.mock import MockI2VProvider


def _seed_live_static(board_id: str, category: str, slug: str) -> str:
    from sqlalchemy import select

    from domains.spaces.assets.models import AssetVersionRecord
    from domains.spaces.models import CellRecord
    from infrastructure.db import session_scope
    from infrastructure.files import workspace as fs_ws

    p = fs_ws.live_path(board_id, category, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (32, 32), (60, 80, 40, 255)).save(p)
    with session_scope() as session:
        cell = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "functional",
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
            ts_ms=1,
            meta_json=None,
        )
        session.add(av)
        session.flush()
        cell.live_asset_version_id = av.id
        return cell.id


def _commit_mock_animation(
    board_id: str,
    cell_id: str,
    *,
    job_id: str = "export-anim-job",
    prompt: str = "chimera breathing fire",
) -> None:
    proposal_dir = manifest_io.proposal_dir(board_id, cell_id, job_id)
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), (200, 100, 100, 255)).save(buf, format="PNG")
    spec = AnimateSpec(
        job_id=job_id,
        cell_id=cell_id,
        source_png=buf.getvalue(),
        source_asset_version_id=None,
        source_basename="seed.png",
        proposal_dir=proposal_dir,
        fps=10,
        duration_ms=500,
        candidates=3,
        encoding="gif",
        loop_strategy="crossfade",
        animation_prompt=prompt,
    )
    animate_space(spec, MockI2VProvider(), NoopSink())
    anim_services.commit_proposal(board_id, cell_id, job_id, proposal_index=0)


def test_export_stages_include_animation_wiring():
    names = [s.__name__ for s in EXPORT_STAGES]
    assert "stage_animation_wiring" in names
    assert names.index("stage_animation_wiring") == names.index("stage_asset_wiring") + 1


def test_animation_wiring_skipped_without_store():
    cat = default_catalog_dict("00000000-0000-4000-8000-000000000001", "X")
    res = run_board_export("00000000-0000-4000-8000-000000000001", cat)
    assert res.ok, res.errors
    panel = next(s for s in res.project["spaces"] if s["id"] == "space_panel_panel_left_top")
    assert panel["assets"]["animation"] is None


def test_animation_wiring_exports_metadata_and_file(
    isolated_repo, seeded_board, board_id, tmp_path
):
    from boardfactory import boards as bf_boards
    from infrastructure import board_store as bs

    cell_id = _seed_live_static(board_id, "panels", "panel_left_top")
    _commit_mock_animation(board_id, cell_id, prompt="chimera breathing fire")

    cat = bf_boards.default_catalog_dict(board_id, seeded_board.project)
    out_root = tmp_path / "bundle"
    res = run_board_export(
        board_id,
        cat,
        options=BoardExportOptions(store=bs.get_store(), bundle_root=out_root),
    )
    assert res.ok, res.errors

    panel = next(s for s in res.project["spaces"] if s["id"] == "space_panel_panel_left_top")
    anim = panel["assets"]["animation"]
    assert isinstance(anim, dict)
    assert anim["path"] == "assets/spaces/panel_left_top/animation_live.gif"
    assert anim["encoding"] == "gif"
    assert anim["fps"] == 10
    assert anim["duration_ms"] == 500
    assert anim["frame_count"] > 0
    assert anim["loop_strategy"] == "crossfade"
    assert anim["provider"] == "mock"
    assert anim["animation_prompt"] == "chimera breathing fire"

    copied = out_root / "assets" / "spaces" / "panel_left_top" / "animation_live.gif"
    assert copied.is_file()
    assert copied.stat().st_size > 0

    pj = json.loads((out_root / "project.json").read_text(encoding="utf-8"))
    exported = next(s for s in pj["spaces"] if s["id"] == "space_panel_panel_left_top")
    assert exported["assets"]["animation"]["animation_prompt"] == "chimera breathing fire"


def test_live_animations_by_panel_slug(isolated_repo, seeded_board, board_id):
    cell_id = _seed_live_static(board_id, "panels", "panel_right_mid")
    _commit_mock_animation(board_id, cell_id, job_id="slug-map")
    m = anim_repo.live_animations_by_panel_slug(board_id)
    assert "panel_right_mid" in m
    assert m["panel_right_mid"].cell_id == cell_id

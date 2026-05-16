"""End-to-end test for ``animate_space`` against the offline mock provider."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from space_animations.ops.animate_space import AnimateSpec, animate_space
from space_animations.ops.progress import NoopSink
from space_animations.providers.mock import MockI2VProvider
from space_animations.schemas.manifest import ProposalManifest


def _png_bytes(size=(32, 32), color=(120, 60, 40, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _spec(tmp_path, **overrides) -> AnimateSpec:
    base = dict(
        job_id="job-test",
        cell_id="cell-1",
        source_png=_png_bytes(),
        source_asset_version_id=42,
        source_basename="src.png",
        proposal_dir=tmp_path / "_proposals" / "job-test",
        fps=10,
        duration_ms=500,
        candidates=3,
        encoding="gif",
        loop_strategy="crossfade",
    )
    base.update(overrides)
    return AnimateSpec(**base)


def test_animate_writes_three_gif_candidates_and_manifest(tmp_path):
    result = animate_space(_spec(tmp_path), MockI2VProvider(), NoopSink())

    assert len(result.candidates) == 3
    for i, rec in enumerate(result.candidates):
        assert rec.index == i
        assert rec.filename == f"{i}.gif"
        assert rec.encoding == "gif"
        assert rec.loop_strategy == "crossfade"
        assert (result.spec.proposal_dir / rec.filename).is_file()

    manifest_path = result.manifest_path
    assert manifest_path.is_file()
    parsed = ProposalManifest.model_validate_json(manifest_path.read_text())
    assert parsed.job_id == "job-test"
    assert parsed.cell_id == "cell-1"
    assert parsed.source_asset_version_id == 42
    assert parsed.provider == "mock"
    assert len(parsed.candidates) == 3
    assert parsed.params.fps == 10
    assert parsed.params.encoding == "gif"


def test_animate_apng_encoding(tmp_path):
    result = animate_space(
        _spec(tmp_path, encoding="apng"),
        MockI2VProvider(),
        NoopSink(),
    )
    assert result.candidates
    for rec in result.candidates:
        assert rec.filename.endswith(".apng")
        assert (result.spec.proposal_dir / rec.filename).is_file()
    parsed = ProposalManifest.model_validate_json(result.manifest_path.read_text())
    assert parsed.params.encoding == "apng"


def test_each_candidate_is_distinct(tmp_path):
    result = animate_space(_spec(tmp_path), MockI2VProvider(), NoopSink())
    digests = [r.sha256 for r in result.candidates]
    assert len(set(digests)) == len(digests), "mock candidates should differ"


def test_invalid_encoding_raises(tmp_path):
    with pytest.raises(ValueError, match="encoding"):
        animate_space(
            _spec(tmp_path, encoding="webm"),
            MockI2VProvider(),
            NoopSink(),
        )


def test_invalid_loop_strategy_raises(tmp_path):
    with pytest.raises(ValueError, match="loop_strategy"):
        animate_space(
            _spec(tmp_path, loop_strategy="bounce"),
            MockI2VProvider(),
            NoopSink(),
        )


def test_empty_source_png_raises(tmp_path):
    with pytest.raises(ValueError, match="source_png"):
        animate_space(
            _spec(tmp_path, source_png=b""),
            MockI2VProvider(),
            NoopSink(),
        )


def test_manifest_is_valid_json(tmp_path):
    result = animate_space(_spec(tmp_path), MockI2VProvider(), NoopSink())
    raw = json.loads(result.manifest_path.read_text())
    assert isinstance(raw, dict)
    assert raw["candidates"][0]["filename"] == "0.gif"

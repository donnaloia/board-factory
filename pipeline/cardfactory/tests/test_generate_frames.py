"""Integration-level test for the generate_frames op using the mock provider."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cardfactory.ops.generate_frames import generate_frames
from cardfactory.providers.mock import MockCardProvider


class _CaptureSink:
    def __init__(self):
        self.events = []

    def emit(self, step, detail="", *, pct=None):
        self.events.append((step, detail, pct))


def test_generate_frames_writes_three_pngs():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "candidates"
        sink = _CaptureSink()

        candidates = generate_frames(
            deck_id="test-deck",
            job_id="job-abc",
            canvas=(720, 1008),
            style_prompt="pixel art fantasy",
            palette_colors=[(128, 64, 32)],
            provider=MockCardProvider(),
            output_dir=out_dir,
            sink=sink,
        )

        assert len(candidates) == 3
        for i in range(3):
            png = out_dir / f"candidate_{i}.png"
            assert png.exists(), f"candidate_{i}.png missing"
            manifest = out_dir / f"candidate_{i}_manifest.json"
            assert manifest.exists()


def test_generate_frames_candidate_descriptors():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "candidates"
        sink = _CaptureSink()

        candidates = generate_frames(
            deck_id="test-deck",
            job_id="job-xyz",
            canvas=(720, 1008),
            style_prompt="",
            palette_colors=[],
            provider=MockCardProvider(),
            output_dir=out_dir,
            sink=sink,
        )

        for i, c in enumerate(candidates):
            assert c["candidate_index"] == i
            assert "inner_rect" in c
            assert c["inner_rect"]["x"] >= 0
            assert c["m_chrome_paint_hash"] is not None
            assert "job-xyz" in c["rel_path"]


def test_generate_frames_png_size():
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "candidates"
        sink = _CaptureSink()

        generate_frames(
            deck_id="d",
            job_id="j",
            canvas=(720, 1008),
            style_prompt="",
            palette_colors=[],
            provider=MockCardProvider(),
            output_dir=out_dir,
            sink=sink,
        )

        img = Image.open(str(out_dir / "candidate_0.png"))
        assert img.size == (720, 1008)

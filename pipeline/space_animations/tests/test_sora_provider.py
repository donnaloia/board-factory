"""Tests for the Sora-backed I2V provider.

The actual ``POST /v1/videos`` HTTP call + polling + MP4 download are
exercised under ``required_permissions: ["full_network"]`` only — these
tests cover the parts that don't need network or ffmpeg: padding the
source onto a Sora-compatible canvas, cropping the cell region back out,
frame resampling, prompt composition, cost estimate, factory aliases,
and gating.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from space_animations.providers.factory import select_provider
from space_animations.providers.sora import (
    SoraI2VProvider,
    _compose_sora_prompt,
    _crop_and_resize,
    _pad_to_target,
    _pick_target_size,
    _resample_frames,
)
from space_animations.providers._motion_director import (
    COST_PER_CALL_USD as _VISION_COST_USD,
)


# ────────────────────────── target size selection ─────────────────────


def test_pick_target_size_landscape_for_square_ish_cells():
    assert _pick_target_size((260, 240)) == "1280x720"
    assert _pick_target_size((100, 100)) == "1280x720"


def test_pick_target_size_portrait_for_tall_cells():
    assert _pick_target_size((240, 480)) == "720x1280"


# ────────────────────────── padding ─────────────────────────


def test_pad_to_target_centres_source_and_returns_crop_box():
    source = Image.new("RGBA", (260, 240), (200, 50, 50, 255))
    png_bytes, box = _pad_to_target(source, "1280x720")

    padded = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    assert padded.size == (1280, 720)

    x0, y0, x1, y1 = box
    # Aspect ratio preserved: 260:240 fits to height 720 → width 780.
    assert (x1 - x0) == pytest.approx(780, abs=1)
    assert (y1 - y0) == pytest.approx(720, abs=1)
    assert x0 == (1280 - (x1 - x0)) // 2
    assert y0 == 0


def test_pad_to_target_uses_black_outside_source():
    source = Image.new("RGBA", (260, 240), (255, 255, 255, 255))
    png_bytes, box = _pad_to_target(source, "1280x720")
    padded = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    # Top-left corner is outside the centred source → black padding.
    assert padded.getpixel((0, 0)) == (0, 0, 0)
    # A pixel inside the source region should be white.
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    assert padded.getpixel((cx, cy)) == (255, 255, 255)


# ────────────────────────── cropping ─────────────────────────


def test_crop_and_resize_returns_native_dimensions():
    canvas = Image.new("RGBA", (1280, 720), (10, 20, 30, 255))
    crop_box = (250, 0, 1030, 720)  # 780 × 720
    out = _crop_and_resize(canvas, crop_box, (260, 240))
    assert out.size == (260, 240)
    assert out.mode == "RGBA"


# ────────────────────────── frame resampling ─────────────────────────


def test_resample_frames_emits_target_count():
    src = [Image.new("RGBA", (4, 4), (i, i, i, 255)) for i in range(96)]
    out = _resample_frames(
        src, source_seconds=4.0, target_fps=30, target_duration_ms=3000
    )
    # 30 fps × 3 s = 90 frames.
    assert len(out) == 90


def test_resample_frames_caps_at_source_length_when_window_overflows():
    src = [Image.new("RGBA", (4, 4), (0, 0, 0, 255)) for _ in range(10)]
    out = _resample_frames(
        src, source_seconds=1.0, target_fps=30, target_duration_ms=10_000
    )
    # No matter how long the target window is, no output frame is
    # beyond the source length — they're clamped to the last frame.
    assert all(f.size == (4, 4) for f in out)


def test_resample_frames_rejects_empty_source():
    with pytest.raises(RuntimeError, match="zero decodable frames"):
        _resample_frames([], source_seconds=4.0, target_fps=30, target_duration_ms=3000)


# ────────────────────────── prompt composition ─────────────────────────


def test_compose_sora_prompt_carries_user_direction_and_plan():
    out = _compose_sora_prompt(
        "chimera breathing fire",
        "Central jaws open and a short orange flame plume jets right.",
    )
    assert "chimera breathing fire" in out
    assert "flame plume" in out
    assert "Preserve composition" in out


def test_compose_sora_prompt_falls_back_to_user_when_plan_empty():
    out = _compose_sora_prompt("skeleton bones falling off", "")
    assert "skeleton bones falling off" in out
    assert "Motion: skeleton bones falling off" in out


# ────────────────────────── cost estimate ──────────────────────────


def test_cost_estimate_uses_per_second_pricing():
    p = SoraI2VProvider(api_key="k", model="sora-2", seconds=4)
    # 1 vision call + 3 candidates × 4 s × $0.10 = $0.005 + $1.20
    expected = _VISION_COST_USD + 3 * 4 * 0.10
    assert p.cost_estimate(candidates=3, duration_ms=3000) == pytest.approx(expected)


def test_cost_estimate_pro_is_more_expensive_than_base():
    base = SoraI2VProvider(api_key="k", model="sora-2", seconds=4)
    pro = SoraI2VProvider(api_key="k", model="sora-2-pro", seconds=4)
    assert pro.cost_estimate(candidates=3, duration_ms=3000) > base.cost_estimate(
        candidates=3, duration_ms=3000
    )


def test_cost_estimate_independent_of_target_duration_ms():
    """Sora bills by its own ``seconds`` field, not by the output
    duration we resample to."""
    p = SoraI2VProvider(api_key="k", model="sora-2", seconds=4)
    assert p.cost_estimate(candidates=3, duration_ms=1000) == p.cost_estimate(
        candidates=3, duration_ms=10_000
    )


# ────────────────────────── factory aliases ─────────────────────


def test_factory_sora_alias_returns_sora_2():
    p = select_provider("sora", openai_api_key="k")
    assert isinstance(p, SoraI2VProvider)
    assert p.model == "sora-2"


def test_factory_sora_2_alias_returns_sora_2():
    p = select_provider("sora-2", openai_api_key="k")
    assert p.model == "sora-2"


def test_factory_sora_pro_alias_returns_sora_2_pro():
    p = select_provider("sora-2-pro", openai_api_key="k")
    assert p.model == "sora-2-pro"


def test_factory_sora_without_key_raises():
    with pytest.raises(RuntimeError, match="Sora animation provider"):
        select_provider("sora", openai_api_key=None)
    with pytest.raises(RuntimeError, match="Sora animation provider"):
        select_provider("sora", openai_api_key="")


def test_factory_sora_pro_without_key_raises():
    with pytest.raises(RuntimeError, match="Sora animation provider"):
        select_provider("sora-2-pro", openai_api_key="")


def test_factory_sora_seconds_env_override(monkeypatch):
    monkeypatch.setenv("SPACE_ANIMATIONS_SORA_SECONDS", "8")
    p = select_provider("sora", openai_api_key="k")
    assert isinstance(p, SoraI2VProvider)
    assert p.seconds == 8


def test_factory_sora_seconds_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SPACE_ANIMATIONS_SORA_SECONDS", "9")
    p = select_provider("sora", openai_api_key="k")
    assert p.seconds == 4


def test_factory_sora_model_env_override(monkeypatch):
    monkeypatch.setenv("SPACE_ANIMATIONS_SORA_MODEL", "sora-2-pro")
    p = select_provider("sora", openai_api_key="k")
    assert p.model == "sora-2-pro"


# ────────────────────────── generate-time gates ─────────────────────


def _png(size=(8, 8), color=(0, 0, 0, 255)) -> bytes:
    src = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    return buf.getvalue()


def test_generate_without_key_raises():
    p = SoraI2VProvider(api_key="")
    with pytest.raises(RuntimeError, match="user's OpenAI API key"):
        p.generate(_png(), fps=30, duration_ms=3000, candidates=1, animation_prompt="x")


def test_generate_without_prompt_raises():
    p = SoraI2VProvider(api_key="k")
    with pytest.raises(RuntimeError, match="animation_prompt"):
        p.generate(_png(), fps=30, duration_ms=3000, candidates=1, animation_prompt="  ")


def test_generate_with_invalid_seconds_raises():
    p = SoraI2VProvider(api_key="k", seconds=7)
    with pytest.raises(RuntimeError, match="seconds"):
        p.generate(_png(), fps=30, duration_ms=3000, candidates=1, animation_prompt="x")


def test_model_id_includes_model_and_seconds():
    p = SoraI2VProvider(api_key="k", model="sora-2-pro", seconds=8)
    assert "sora-2-pro" in p.model_id
    assert "8s" in p.model_id

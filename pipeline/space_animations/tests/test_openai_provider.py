"""Tests for the OpenAI / ChatGPT-backed I2V provider.

The actual ``/v1/images/edits`` HTTP call is exercised under
``required_permissions: ["full_network"]`` only — these tests cover the
parts that don't need network: the morph helper, cost estimate, gating
in the provider factory, the ``_to_api_size`` resize, and the
edit-prompt composition that wraps each candidate's plan.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from space_animations.providers.factory import select_provider
from space_animations.providers.openai import (
    OpenAII2VProvider,
    _compose_edit_prompt,
    _morph_loop_frames,
    _to_api_size,
)
from space_animations.providers._motion_director import (
    COST_PER_CALL_USD as _VISION_COST_USD,
)


# ────────────────────────── _morph_loop_frames ──────────────────────────


def _solid(size, color):
    return Image.new("RGBA", size, color)


def test_morph_loop_frames_endpoints_match_source():
    """First and last frames must equal the source for a perfect loop."""
    source = _solid((16, 16), (200, 50, 50, 255))
    variant = _solid((16, 16), (50, 50, 200, 255))
    frames = _morph_loop_frames(source, variant, frame_count=5)
    assert frames[0].tobytes() == source.tobytes()
    assert frames[-1].tobytes() == source.tobytes()


def test_morph_loop_frames_midpoint_blends_to_variant():
    """Middle frame should be ~50/50 (halfway through the triangle wave)."""
    source = _solid((4, 4), (200, 0, 0, 255))
    variant = _solid((4, 4), (0, 0, 200, 255))
    frames = _morph_loop_frames(source, variant, frame_count=3)
    mid_pixel = frames[1].getpixel((0, 0))
    assert mid_pixel[0] < 50  # red mostly faded
    assert mid_pixel[2] > 150  # blue mostly emerged


def test_morph_loop_frames_count_matches_request():
    source = _solid((4, 4), (10, 20, 30, 255))
    variant = _solid((4, 4), (200, 200, 200, 255))
    frames = _morph_loop_frames(source, variant, frame_count=12)
    assert len(frames) == 12


def test_morph_loop_frames_resizes_variant_to_source():
    """Variants from gpt-image-2 come back at 1024x1024 — must resize down."""
    source = _solid((8, 8), (10, 10, 10, 255))
    variant = _solid((1024, 1024), (250, 250, 250, 255))
    frames = _morph_loop_frames(source, variant, frame_count=4)
    assert all(f.size == source.size for f in frames)


def test_morph_loop_frames_rejects_too_few_frames():
    source = _solid((4, 4), (0, 0, 0, 255))
    with pytest.raises(ValueError, match="frame_count"):
        _morph_loop_frames(source, source, frame_count=1)


# ────────────────────────── cost estimate ──────────────────────────


def test_cost_estimate_grows_by_one_edit_per_extra_candidate():
    """Each extra candidate adds exactly one /images/edits call.

    The vision call cost is paid once per job, so the per-job total is
    ``vision + N * edit`` and the *delta* between N and N+1 candidates
    must be exactly one image-edit call.
    """
    p = OpenAII2VProvider(api_key="not-used-for-estimate")
    one = p.cost_estimate(candidates=1, duration_ms=3000)
    three = p.cost_estimate(candidates=3, duration_ms=3000)
    assert three - one == pytest.approx(2 * (one - _VISION_COST_USD))
    assert one > _VISION_COST_USD


def test_cost_estimate_includes_vision_pass_overhead():
    """Job cost must account for the one-shot gpt-4o vision pass."""
    p = OpenAII2VProvider(api_key="not-used-for-estimate")
    edits_only = 3 * 0.011
    assert p.cost_estimate(candidates=3, duration_ms=3000) > edits_only


def test_cost_estimate_independent_of_duration():
    """Morph is local — duration shouldn't change OpenAI billing."""
    p = OpenAII2VProvider(api_key="not-used-for-estimate")
    short = p.cost_estimate(candidates=3, duration_ms=1000)
    long_ = p.cost_estimate(candidates=3, duration_ms=10000)
    assert short == long_


def test_model_id_includes_morph_and_vision_markers():
    """Manifest readers should be able to tell this is hybrid (img + morph + vision)."""
    p = OpenAII2VProvider(api_key="x")
    assert "morph" in p.model_id
    assert "vision" in p.model_id


# ────────────────────────── edit prompt composition ─────────────────────


def test_compose_edit_prompt_carries_user_direction_and_plan():
    out = _compose_edit_prompt(
        "chimera breathing fire",
        "Open the central jaws and add an orange flame plume jetting right.",
    )
    assert "chimera breathing fire" in out
    assert "flame plume" in out
    assert "Same scene" in out


def test_compose_edit_prompt_drops_old_aesthetic_presets():
    """Glow / shimmer / drift presets must be gone from the prompt surface."""
    out = _compose_edit_prompt(
        "chimera breathing fire", "tailored destination still"
    )
    lowered = out.lower()
    assert "glow" not in lowered
    assert "shimmer" not in lowered
    assert "drift" not in lowered


def test_compose_edit_prompt_falls_back_to_user_when_plan_empty():
    out = _compose_edit_prompt("skeleton bones falling off", "")
    assert "skeleton bones falling off" in out
    assert "Destination still: skeleton bones falling off" in out


# ────────────────────────── factory gating ──────────────────────────


def test_factory_openai_alias_returns_openai():
    p = select_provider("openai", openai_api_key="k")
    assert p.name == "openai"
    assert isinstance(p, OpenAII2VProvider)


def test_factory_chatgpt_alias_returns_openai():
    p = select_provider("chatgpt", openai_api_key="k")
    assert isinstance(p, OpenAII2VProvider)


def test_factory_openai_without_key_raises():
    with pytest.raises(RuntimeError, match="OpenAI / ChatGPT API"):
        select_provider("openai", openai_api_key=None)
    with pytest.raises(RuntimeError, match="OpenAI / ChatGPT API"):
        select_provider("openai", openai_api_key="")


def test_factory_mock_ignores_key():
    p = select_provider("mock")
    assert p.name == "mock"


def test_factory_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown space-animations provider"):
        select_provider("not-a-real-provider", openai_api_key="k")


# ────────────────────────── source-png resize ──────────────────────────


def test_to_api_size_pads_to_1024():
    """OpenAI edits endpoint requires a fixed 1024×1024 canvas."""
    src = _solid((8, 8), (123, 234, 56, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    out = _to_api_size(buf.getvalue())
    img = Image.open(out)
    assert img.size == (1024, 1024)


# ────────────────────────── generate-time gate ──────────────────────────


def test_generate_without_key_raises():
    """Even the dataclass must refuse when generate is called without a key."""
    p = OpenAII2VProvider(api_key="")
    src = _solid((8, 8), (0, 0, 0, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    with pytest.raises(RuntimeError, match="user's OpenAI API key"):
        p.generate(
            buf.getvalue(),
            fps=10,
            duration_ms=200,
            candidates=1,
            animation_prompt="anything",
        )


def test_generate_without_prompt_raises():
    """Defense in depth: provider also refuses empty motion direction."""
    p = OpenAII2VProvider(api_key="key")
    src = _solid((8, 8), (0, 0, 0, 255))
    buf = io.BytesIO()
    src.save(buf, format="PNG")
    with pytest.raises(RuntimeError, match="animation_prompt"):
        p.generate(
            buf.getvalue(),
            fps=10,
            duration_ms=200,
            candidates=1,
            animation_prompt="   ",
        )

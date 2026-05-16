"""Tests for the gpt-4o motion-director vision pass.

The actual HTTPS call to ``/v1/chat/completions`` is exercised under
``required_permissions: ["full_network"]`` only — these tests cover the
no-network branches: parser tolerance, fallbacks when the API key is
missing, and the cycle behaviour when the model returns fewer plans
than requested.
"""

from __future__ import annotations

import json

from space_animations.providers._motion_director import (
    _parse_plans,
    plan_motion_variants,
)


# ────────────────────────── _parse_plans ──────────────────────────


def test_parse_plans_accepts_dict_form():
    payload = json.dumps(
        {"plans": ["open jaws + flame plume", "head tilts and arcs fire upward", "wide stance"]}
    )
    plans = _parse_plans(payload, n=3)
    assert plans == [
        "open jaws + flame plume",
        "head tilts and arcs fire upward",
        "wide stance",
    ]


def test_parse_plans_accepts_bare_array():
    payload = json.dumps(["a", "b", "c"])
    plans = _parse_plans(payload, n=3)
    assert plans == ["a", "b", "c"]


def test_parse_plans_accepts_first_list_value_in_dict():
    """Models sometimes wrap the array under a key other than ``plans``."""
    payload = json.dumps({"variants": ["a", "b"]})
    plans = _parse_plans(payload, n=2)
    assert plans == ["a", "b"]


def test_parse_plans_cycles_when_short():
    """If the model returns fewer than N, cycle to fill — never crash."""
    payload = json.dumps({"plans": ["a", "b"]})
    plans = _parse_plans(payload, n=5)
    assert plans == ["a", "b", "a", "b", "a"]


def test_parse_plans_trims_and_drops_empty():
    payload = json.dumps({"plans": ["  open jaws  ", "", "   "]})
    plans = _parse_plans(payload, n=2)
    assert plans == ["open jaws", "open jaws"]


def test_parse_plans_returns_none_for_invalid_json():
    assert _parse_plans("not json at all", n=3) is None


def test_parse_plans_returns_none_for_empty_list():
    payload = json.dumps({"plans": []})
    assert _parse_plans(payload, n=3) is None


def test_parse_plans_returns_none_for_non_list_payload():
    payload = json.dumps({"plans": "open jaws"})
    assert _parse_plans(payload, n=3) is None


def test_parse_plans_caps_when_long():
    payload = json.dumps({"plans": ["a", "b", "c", "d", "e"]})
    plans = _parse_plans(payload, n=3)
    assert plans == ["a", "b", "c"]


# ────────────────────────── plan_motion_variants fallbacks ─────────


def test_plan_motion_variants_returns_empty_for_zero_candidates():
    assert (
        plan_motion_variants(
            source_png=b"\x89PNG", animation_prompt="anything", n=0, api_key="k"
        )
        == []
    )


def test_plan_motion_variants_falls_back_without_api_key():
    """No key → no vision call → repeat the user prompt N times."""
    plans = plan_motion_variants(
        source_png=b"\x89PNG",
        animation_prompt="chimera breathing fire",
        n=3,
        api_key="",
    )
    assert plans == ["chimera breathing fire"] * 3


def test_plan_motion_variants_falls_back_without_user_prompt():
    """Empty prompt → fall back; we never invent direction silently."""
    plans = plan_motion_variants(
        source_png=b"\x89PNG", animation_prompt="   ", n=2, api_key="key"
    )
    assert plans == ["   ", "   "]

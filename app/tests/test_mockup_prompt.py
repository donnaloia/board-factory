"""Tests for mockup AI prompt composition."""

from __future__ import annotations

from services import mockup_prompt as mp


def test_layout_context_counts():
    cat = {
        "board_size": [1920, 1080],
        "board_spaces": {
            "designs": [
                {"id": "a", "positions": ["x", "y", "z"]},
                {"id": "b", "positions": ["p"]},
            ]
        },
        "feature_panels": {"panels": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
    }
    s = mp.layout_context_for_mockup(cat)
    assert "1920×1080" in s or ("1920" in s and "1080" in s)
    assert "4" in s  # total positions
    assert "2 distinct space art designs" in s
    assert "3 illustrated functional feature-panel" in s


def test_compose_includes_style_when_present():
    cat = {
        "board_size": [1280, 720],
        "board_spaces": {"designs": []},
        "feature_panels": {"panels": []},
        "style": {"prompt": "Neon cyberpunk diner"},
    }
    out = mp.compose_mockup_image_prompt("My board", cat, framing_suffix=" — END.")
    assert "My board" in out
    assert "Neon cyberpunk diner" in out
    assert out.endswith(" — END.")


def test_compose_omits_empty_style():
    cat = {
        "board_size": [1920, 1080],
        "board_spaces": {"designs": [{"id": "x", "positions": ["a"]}]},
        "feature_panels": {"panels": [{"id": "p"}]},
        "style": {"prompt": ""},
    }
    out = mp.compose_mockup_image_prompt("Test", cat, framing_suffix="")
    assert "Overall art direction" not in out

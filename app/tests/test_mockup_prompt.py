"""Tests for mockup AI prompt composition."""

from __future__ import annotations

from services import mockup_prompt as mp


def test_layout_context_counts():
    cat = {
        "board_size": [1920, 1080],
        "board_spaces": {
            "layout": {
                "top_row": {"count": 12},
                "bottom_row": {"count": 12},
                "left_col": {"count": 5},
                "right_col": {"count": 5},
            },
            "designs": [
                {"id": "a", "positions": ["x", "y", "z"]},
                {"id": "b", "positions": ["p"]},
            ],
        },
        "feature_panels": {"panels": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        "centerpiece": {"bbox": [700, 180, 1220, 900]},
    }
    s = mp.layout_context_for_mockup(cat)
    assert "1920×1080" in s or ("1920" in s and "1080" in s)
    assert "orthographic" in s or "top-down" in s
    assert "4" in s  # total positions
    assert "2 distinct space-art" in s
    assert "12 along the top" in s
    assert "5 along the left" in s
    assert "3 distinct rectangular functional" in s
    assert "700" in s and "1220" in s  # centerpiece bbox hint


def test_layout_context_panel_left_right_split():
    """Panels with bboxes split by board midpoint → left/right counts."""
    cat = {
        "board_size": [1920, 1080],
        "board_spaces": {"layout": {}, "designs": []},
        "feature_panels": {
            "panels": [
                {"id": "L", "bbox": [100, 0, 200, 100]},
                {"id": "R", "bbox": [1700, 0, 1800, 100]},
            ]
        },
        "centerpiece": {},
    }
    s = mp.layout_context_for_mockup(cat)
    assert "1 on the left half" in s
    assert "1 on the right half" in s


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

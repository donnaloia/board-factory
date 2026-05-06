"""Tests for mockup AI prompt composition."""

from __future__ import annotations

from domains.boards import mockup_prompt as mp


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


def test_default_catalog_twelve_panel_grid_labels():
    from boardfactory.boards import default_catalog_dict

    cat = default_catalog_dict("test-board", "Test")
    s = mp.layout_context_for_mockup(cat)
    assert "outer-left strip" in s
    assert "inner-left strip" in s
    assert "inner-right strip" in s
    assert "outer-right strip" in s
    assert "twelve" in s.lower() or "12" in s
    assert "260×240" in s or ("260" in s and "240" in s)
    assert "700" in s and "1220" in s
    assert "Reserve the horizontal centerpiece band" in s or "x < 700" in s


def test_layout_context_panel_left_right_split():
    """Two bbox panels far apart → clustered columns (grid paragraph, not half-board counts)."""
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
    assert "Functional UI panels" in s
    assert "column 1 from the left" in s
    assert "column 2 from the left" in s


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

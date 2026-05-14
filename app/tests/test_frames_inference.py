"""Unit tests for the deterministic-cleanup math in ``frames_inference``.

These never touch the network or a job runner — pure geometry, so they
run in milliseconds. Higher-level Atelier wiring is covered by
``test_frame_atelier_routes.py`` (commit flow + Approach D rotation).
"""

from __future__ import annotations

from PIL import Image, ImageDraw


# ────────────────────────── primitives ──────────────────────────


def test_threshold_binarizes_grey():
    from boardfactory import frames_inference as fi

    src = Image.new("L", (8, 8), 0)
    ImageDraw.Draw(src).rectangle((2, 2, 5, 5), fill=200)
    out = fi.threshold(src, level=128)
    assert out.getpixel((0, 0)) == 0
    assert out.getpixel((3, 3)) == 255


def test_morph_close_fills_one_pixel_gap():
    from boardfactory import frames_inference as fi

    src = Image.new("L", (16, 16), 0)
    ImageDraw.Draw(src).rectangle((2, 2, 13, 13), fill=255)
    src.putpixel((7, 2), 0)  # one-pixel gap on the top edge

    out = fi.morph_close(src, radius=2)
    assert out.getpixel((7, 2)) == 255


def test_bbox_area_fraction():
    from boardfactory import frames_inference as fi

    assert fi.bbox_area_fraction((0, 0, 100, 100), (100, 100)) == 1.0
    assert fi.bbox_area_fraction((25, 25, 75, 75), (100, 100)) == 0.25


def test_grid_snap_bbox_rounds_outward_at_lower_right():
    from boardfactory import frames_inference as fi

    snapped = fi.grid_snap_bbox((3, 3, 10, 10), grid=4, image_size=(16, 16))
    # Lower-right edge should grow outward to next multiple of 4.
    assert snapped[0] == 0 or snapped[0] == 4
    assert snapped[2] >= 12


def test_ring_thickness_estimates_uniform_ring():
    from boardfactory import frames as bf_frames
    from boardfactory import frames_inference as fi

    _hole, rim = bf_frames.derive_masks_from_ring((64, 64), ring_px=6)
    assert fi.ring_thickness(rim) in (5, 6, 7)


# ────────────────────────── candidate pipeline ──────────────────────────


def test_candidate_from_outer_inner_round_trip_matches_ring():
    from boardfactory import frames as bf_frames
    from boardfactory import frames_inference as fi

    size = (64, 64)
    hole, rim = bf_frames.derive_masks_from_ring(size, ring_px=8)
    outer = Image.new("L", size, 255)  # full panel = rim ∪ hole
    inner = hole

    cand = fi.candidate_from_outer_inner(
        source_size=size, outer=outer, inner=inner,
        hole_expand_px=0,
    )
    assert cand.bbox[0] == 0 and cand.bbox[1] == 0
    assert cand.bbox[2] == 64 and cand.bbox[3] == 64
    assert cand.ring_px in (7, 8, 9)
    assert cand.hole_mask.size == size
    assert cand.rim_mask.size == size


def test_candidate_from_ring_is_deterministic_fallback():
    from boardfactory import frames_inference as fi

    cand = fi.candidate_from_ring(source_size=(80, 60), ring_px=5)
    assert cand.bbox == (0, 0, 80, 60)
    assert cand.ring_px == 5
    assert cand.hole_mask.size == (80, 60)
    # Center pixel of the hole should be white; corner should be black.
    assert cand.hole_mask.getpixel((40, 30)) == 255
    assert cand.hole_mask.getpixel((0, 0)) == 0


def test_fit_to_window_regenerates_masks_for_new_bbox():
    from boardfactory import frames_inference as fi

    seed = fi.candidate_from_ring(source_size=(64, 64), ring_px=6)
    refined = fi.fit_to_window(seed, bbox=(8, 8, 56, 56), source_size=(64, 64))
    # The refine path should produce a hole that's strictly smaller
    # than the original (we shrunk the bbox by 8px on every side).
    seed_hole = sum(1 for v in seed.hole_mask.getdata() if v >= 128)
    new_hole = sum(1 for v in refined.hole_mask.getdata() if v >= 128)
    assert new_hole < seed_hole


# ────────────────────────── on-disk pack regression ──────────────────────────


def test_extract_9slice_writes_hole_and_rim_masks(tmp_path):
    from boardfactory import frames as bf_frames

    src = Image.new("RGBA", (64, 64), (40, 40, 40, 255))
    ImageDraw.Draw(src).rectangle((0, 0, 63, 7), fill=(180, 130, 70, 255))
    ImageDraw.Draw(src).rectangle((0, 56, 63, 63), fill=(180, 130, 70, 255))
    ImageDraw.Draw(src).rectangle((0, 0, 7, 63), fill=(180, 130, 70, 255))
    ImageDraw.Draw(src).rectangle((56, 0, 63, 63), fill=(180, 130, 70, 255))

    sl = bf_frames.extract_9slice(src, ring_px=8)
    assert sl.hole_mask is not None
    assert sl.rim_mask is not None

    sl.save(tmp_path)
    # Assert the new files landed alongside the eight sprite PNGs.
    assert (tmp_path / "hole_mask.png").exists()
    assert (tmp_path / "rim_mask.png").exists()
    assert (tmp_path / "corner_tl.png").exists()
    assert (tmp_path / "edge_top.png").exists()

"""Service-layer tests for catalog / generation block.

Phase 1b coverage: read/save round-trips, generation defaults filled in,
write_generation validation + persistence.
"""

from __future__ import annotations

import pytest


def test_load_catalog_round_trip(seeded_board):
    from domains.boards import services as svc_catalog

    data = svc_catalog.load_catalog(seeded_board.id)
    assert data["project"] == "Test Board"
    # Default generation block from domains.boards.create_board.
    gen = data["generation"]
    assert gen["palette_size"] == 36
    assert gen["provider"] == "openai"
    assert gen["openai"]["model"] == "gpt-image-2"
    assert gen["pixellab"]["model"] == "pixflux_sharp"
    assert gen["configured"] is False


def test_safe_load_catalog_returns_none_for_missing(isolated_repo):
    from domains.boards import services as svc_catalog

    assert svc_catalog.safe_load_catalog("does-not-exist") is None


def test_load_catalog_raises_for_missing(isolated_repo):
    from domains.boards import services as svc_catalog

    with pytest.raises(svc_catalog.CatalogNotFound):
        svc_catalog.load_catalog("does-not-exist")


def test_read_generation_fills_defaults_for_partial_block():
    from domains.boards import services as svc_catalog

    block = svc_catalog.read_generation({"generation": {"palette_size": 24}})
    assert block["palette_size"] == 24
    assert block["provider"] == "openai"
    assert block["openai"]["model"] == "gpt-image-2"


def test_write_generation_persists_and_marks_configured(seeded_board):
    from domains.boards import services as svc_catalog

    new_block = svc_catalog.write_generation(
        seeded_board.id,
        {
            "palette_size": 24,
            "provider": "openai",
            "openai": {"model": "gpt-image-1", "quality": "medium"},
            "pixellab": {"model": "pixflux_sharp"},
        },
    )
    assert new_block["configured"] is True

    reloaded = svc_catalog.load_catalog(seeded_board.id)
    assert reloaded["generation"]["palette_size"] == 24
    assert reloaded["generation"]["openai"]["quality"] == "medium"
    # style.palette_size is mirrored so legacy pipeline steps see the new value.
    assert reloaded["style"]["palette_size"] == 24


def test_write_generation_rejects_bad_palette_size(seeded_board):
    from domains.boards import services as svc_catalog

    with pytest.raises(svc_catalog.GenerationValidationError):
        svc_catalog.write_generation(
            seeded_board.id,
            {
                "palette_size": 99,
                "provider": "openai",
                "openai": {"model": "gpt-image-2", "quality": "low"},
                "pixellab": {"model": "pixflux_sharp"},
            },
        )


def test_write_generation_rejects_bad_provider(seeded_board):
    from domains.boards import services as svc_catalog

    with pytest.raises(svc_catalog.GenerationValidationError):
        svc_catalog.write_generation(
            seeded_board.id,
            {
                "palette_size": 36,
                "provider": "bogus",
                "openai": {"model": "gpt-image-2", "quality": "low"},
                "pixellab": {"model": "pixflux_sharp"},
            },
        )


def test_space_kind_persists_on_space_design(seeded_board):
    from domains.boards import services as svc_catalog

    data = svc_catalog.load_catalog(seeded_board.id)
    corner = next(d for d in data["board_spaces"]["designs"] if d["id"] == "corner_tl")
    assert corner.get("space_kind", "standard") == "standard"
    corner["space_kind"] = "event"
    svc_catalog.save_catalog(seeded_board.id, data)
    again = svc_catalog.load_catalog(seeded_board.id)
    corner2 = next(d for d in again["board_spaces"]["designs"] if d["id"] == "corner_tl")
    assert corner2["space_kind"] == "event"



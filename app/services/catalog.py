"""Catalog use cases — relational DB as source of truth.

``board_games`` (+ child tables) hold the canonical board spec. The pipeline
loads a ``Catalog`` model from this layer via ``app.pipeline_adapters`` (no
``catalog.yml`` required at runtime).

Optional ``boards/<id>/catalog.yml`` on disk is still **imported once** when
present and the relational row is missing (legacy checkouts). Use
``sync_disk_yaml_into_relational`` after editing that file by hand.

If the board directory exists (pipeline ``get_board``) but there is still no
catalog in the DB or YAML — e.g. Postgres was recreated while ``boards/`` was
left on disk — we **seed the standard template** via
``boardfactory.boards.default_catalog_dict`` once so the UI can load again.

Public surface:

  - ``load_catalog`` / ``safe_load_catalog`` / ``save_catalog``
  - ``read_generation`` / ``read_generation_block`` / ``write_generation``
  - ``sync_disk_yaml_into_relational``
"""

from __future__ import annotations

from typing import Any

from storage.fs import workspace as fs_ws
from storage.fs import yaml_io as fs_yaml

from services import board_definition as bd


# ────────────────────────── exceptions ──────────────────────────


class CatalogNotFound(LookupError):
    pass


class GenerationValidationError(ValueError):
    pass


# ────────────────────────── generation defaults ──────────────────────────


_VALID_PALETTE_SIZES = (24, 36)
_VALID_PROVIDERS = ("openai", "pixellab", "mock")
_VALID_OPENAI_MODELS = ("gpt-image-1", "gpt-image-2")
_VALID_OPENAI_QUALITIES = ("low", "medium", "high")


def _generation_defaults() -> dict:
    return {
        "palette_size": 36,
        "provider": "openai",
        "openai": {"model": "gpt-image-2", "quality": "low"},
        "pixellab": {"model": "pixflux_sharp"},
        "configured": False,
    }


def read_generation(catalog: dict) -> dict:
    """Return the generation block, filling defaults for missing fields."""
    block = dict(_generation_defaults())
    block["openai"] = dict(block["openai"])
    block["pixellab"] = dict(block["pixellab"])
    existing = catalog.get("generation") if isinstance(catalog, dict) else None
    if not isinstance(existing, dict):
        return block

    if "palette_size" in existing:
        try:
            ps = int(existing["palette_size"])
            if 4 <= ps <= 64:
                block["palette_size"] = ps
        except (TypeError, ValueError):
            pass
    if existing.get("provider") in _VALID_PROVIDERS:
        block["provider"] = existing["provider"]

    oa = existing.get("openai") or {}
    if isinstance(oa, dict):
        if oa.get("model") in _VALID_OPENAI_MODELS:
            block["openai"]["model"] = oa["model"]
        if oa.get("quality") in _VALID_OPENAI_QUALITIES:
            block["openai"]["quality"] = oa["quality"]

    pl = existing.get("pixellab") or {}
    if isinstance(pl, dict):
        # Lazy import: keeps the pipeline package off the hot path of
        # services/catalog (and out of our test harness when it's not needed).
        from boardfactory.providers.pixel.pixellab import PIXELLAB_PRESETS
        if pl.get("model") in PIXELLAB_PRESETS:
            block["pixellab"]["model"] = pl["model"]

    if "configured" in existing:
        block["configured"] = bool(existing["configured"])
    return block


# ────────────────────────── canonical catalog persistence ──────────────────────────


def safe_load_catalog(board_id: str) -> dict[str, Any] | None:
    """Prefer relational storage; migrate from a legacy ``catalog.yml`` if needed."""
    d = bd.load_catalog_dict(board_id)
    if d is not None:
        return d

    yaml_path = fs_ws.catalog_path(board_id)
    yaml_blob = fs_yaml.load_yaml(yaml_path)
    if yaml_blob is not None:
        bd.persist_catalog_dict(board_id, yaml_blob)
        return bd.load_catalog_dict(board_id)

    # Board dirs on disk without DB rows (fresh Postgres, or never-persisted
    # skeleton) — same default template ``create_board`` + the UI normally persist.
    from boardfactory import boards as bf_boards

    info = bf_boards.get_board(board_id)
    if info is not None:
        seed = bf_boards.default_catalog_dict(board_id, info.project)
        bd.persist_catalog_dict(board_id, seed)
        return bd.load_catalog_dict(board_id)

    return None


def load_catalog(board_id: str) -> dict[str, Any]:
    data = safe_load_catalog(board_id)
    if data is None:
        raise CatalogNotFound(board_id)
    return data


def save_catalog(board_id: str, data: dict[str, Any]) -> None:
    """Validate and persist the catalog to relational tables only."""
    bd.persist_catalog_dict(board_id, data)


def sync_disk_yaml_into_relational(board_id: str) -> None:
    """Re-import ``catalog.yml`` after a legacy writer updated the file only."""
    path = fs_ws.catalog_path(board_id)
    blob = fs_yaml.load_yaml(path)
    if blob is None:
        return
    bd.persist_catalog_dict(board_id, blob)


def read_generation_block(board_id: str) -> dict:
    """Convenience: ``read_generation(load_catalog(board_id))`` with a
    ``CatalogNotFound`` if the catalog is missing.
    """
    return read_generation(load_catalog(board_id))


# ────────────────────────── generation block writer ──────────────────────────


def write_generation(board_id: str, body: dict) -> dict:
    """Validate ``body`` and persist as the new ``generation`` block.

    Raises ``GenerationValidationError`` on bad input. On success the
    legacy ``style.palette_size`` is mirrored so old pipeline steps keep
    seeing the right value.
    """
    catalog = load_catalog(board_id)
    current = read_generation(catalog)
    from boardfactory.providers.pixel.pixellab import PIXELLAB_PRESETS

    palette_size = body.get("palette_size", current["palette_size"])
    try:
        palette_size = int(palette_size)
    except (TypeError, ValueError):
        raise GenerationValidationError("palette_size must be an integer")
    if palette_size not in _VALID_PALETTE_SIZES:
        raise GenerationValidationError("palette_size must be 24 or 36")

    provider = body.get("provider", current["provider"])
    if provider not in ("openai", "pixellab"):
        raise GenerationValidationError("provider must be 'openai' or 'pixellab'")

    oa = body.get("openai") or {}
    oa_model = oa.get("model", current["openai"]["model"])
    if oa_model not in _VALID_OPENAI_MODELS:
        raise GenerationValidationError("openai.model must be 'gpt-image-1' or 'gpt-image-2'")
    oa_quality = oa.get("quality", current["openai"]["quality"])
    if oa_quality not in _VALID_OPENAI_QUALITIES:
        raise GenerationValidationError("openai.quality must be low/medium/high")

    pl = body.get("pixellab") or {}
    pl_model = pl.get("model", current["pixellab"]["model"])
    if pl_model not in PIXELLAB_PRESETS:
        raise GenerationValidationError(
            f"pixellab.model must be one of {sorted(PIXELLAB_PRESETS)}"
        )

    new_block = {
        "palette_size": palette_size,
        "provider": provider,
        "openai": {"model": oa_model, "quality": oa_quality},
        "pixellab": {"model": pl_model},
        "configured": True,
    }
    catalog["generation"] = new_block
    style = catalog.setdefault("style", {})
    style["palette_size"] = palette_size
    save_catalog(board_id, catalog)
    return new_block

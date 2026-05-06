"""Boards domain — public service API.

This module is the only door other domains use to read or write boards.
Internally it owns three responsibilities, kept in one file because they
form one cohesive use-case surface:

  1. **Catalog assembly** — joining ``board_games`` + ``cells`` rows back
     into the legacy nested dict consumed by the pipeline + templates,
     and decomposing a validated ``Catalog`` back into those three
     storage shapes on save (rows + cells + body_json).
  2. **Generation block** — read/write the per-board generation settings
     (palette size, provider, model, quality) with explicit validation,
     used by the settings modal.
  3. **Board CRUD** — list/get/create/delete/rename, plus on-disk
     skeleton creation through the ``BoardStore``.

The DB I/O lives in ``boards.repository``; this module is the layer
above it that holds business rules.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from boardfactory import boards as bf_boards
from boardfactory.schemas import Catalog

from domains.boards import repository as boards_repo
from domains.cells.geometry import resolve_position
from infrastructure import board_store as bs
from infrastructure.db import session_scope
from infrastructure.files import workspace as fs_ws
from assets.models import AssetVersionRecord
from domains.boards.models import BoardGameRecord, OwnedBoardRecord
from domains.cells.models import CellRecord


# ────────────────────────── exceptions ──────────────────────────


class BoardNotFound(LookupError):
    pass


class InvalidBoardId(ValueError):
    pass


class BoardExists(ValueError):
    pass


class CatalogNotFound(LookupError):
    pass


class GenerationValidationError(ValueError):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


# ────────────────────────── catalog assembly ──────────────────────────


def _cell_to_design_dict(c: CellRecord) -> dict[str, Any]:
    return {
        "id": c.slug,
        "prompt": c.prompt,
        "space_kind": c.space_kind or "standard",
        "positions": list(c.positions_json or []),
    }


def _cell_to_panel_dict(c: CellRecord) -> dict[str, Any]:
    return {
        "id": c.slug,
        "prompt": c.prompt,
        "needs_active": bool(c.needs_active),
        "active_kind": c.active_kind or "none",
        "bbox": [int(c.bbox_x1 or 0), int(c.bbox_y1 or 0),
                 int(c.bbox_x2 or 0), int(c.bbox_y2 or 0)],
        "target_size": [int(c.target_w or 0), int(c.target_h or 0)],
    }


def _cell_to_centerpiece_dict(c: CellRecord) -> dict[str, Any]:
    return {
        "bbox": [int(c.bbox_x1 or 0), int(c.bbox_y1 or 0),
                 int(c.bbox_x2 or 0), int(c.bbox_y2 or 0)],
        "target_size": [int(c.target_w or 0), int(c.target_h or 0)],
        "prompt": c.prompt,
        "needs_active": bool(c.needs_active),
        "active_kind": c.active_kind or "none",
    }


def _row_to_catalog_dict(row: BoardGameRecord, cells: list[CellRecord]) -> dict[str, Any]:
    """Reassemble a ``Catalog``-shaped dict from row + cells + body_json."""
    body = dict(row.body_json or {})

    body["project"] = row.project
    body["board_size"] = [int(row.board_size_w), int(row.board_size_h)]

    # ``palette_size`` is mirrored back into ``style`` by Pydantic's
    # ``_sync_palette_size`` validator so legacy pipeline code that reads
    # ``catalog.style.palette_size`` keeps working.
    body["style"] = {
        "reference_image": row.style_reference_image,
        "prompt": row.style_prompt,
        "palette_size": int(row.palette_size),
    }

    spaces = sorted(
        (c for c in cells if c.kind == "space"),
        key=lambda c: c.position_index,
    )
    panels = sorted(
        (c for c in cells if c.kind == "panel"),
        key=lambda c: c.position_index,
    )
    cp_cells = [c for c in cells if c.kind == "centerpiece"]
    if not cp_cells:
        # Legacy boards or boards mid-creation — fall back to a zero
        # centerpiece so Pydantic validation doesn't blow up the page.
        body["centerpiece"] = {
            "bbox": [0, 0, 0, 0],
            "target_size": [0, 0],
            "prompt": "",
            "needs_active": False,
            "active_kind": "none",
        }
    else:
        body["centerpiece"] = _cell_to_centerpiece_dict(cp_cells[0])

    layout = (body.get("board_spaces") or {}).get("layout") or {}
    body["board_spaces"] = {
        "layout": layout,
        "designs": [_cell_to_design_dict(c) for c in spaces],
    }
    body["feature_panels"] = {
        "panels": [_cell_to_panel_dict(c) for c in panels],
    }

    body["generation"] = {
        "palette_size": int(row.palette_size),
        "provider": row.provider,
        "openai": {
            "model": row.openai_model,
            "quality": row.openai_quality,
        },
        "pixellab": {"model": row.pixellab_model},
        "configured": bool(row.generation_configured),
    }
    body["frame"] = {
        "enabled": bool(row.frame_enabled),
        "apply_to_panels": bool(row.frame_apply_to_panels),
        "apply_to_spaces": bool(row.frame_apply_to_spaces),
    }
    return body


def _split_catalog(cat: Catalog) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(column_values, body_json)`` from a validated ``Catalog``.

    The cells (designs / panels / centerpiece) are *not* returned here;
    callers persist them via ``_replace_cells`` in the same transaction.
    """
    columns = {
        "project": cat.project,
        "board_size_w": int(cat.board_size[0]),
        "board_size_h": int(cat.board_size[1]),
        "style_reference_image": cat.style.reference_image,
        "style_prompt": cat.style.prompt,
        "palette_size": int(cat.generation.palette_size),
        "provider": cat.generation.provider,
        "openai_model": cat.generation.openai.model,
        "openai_quality": cat.generation.openai.quality,
        "pixellab_model": cat.generation.pixellab.model,
        "generation_configured": bool(cat.generation.configured),
        "frame_enabled": bool(cat.frame.enabled),
        "frame_apply_to_panels": bool(cat.frame.apply_to_panels),
        "frame_apply_to_spaces": bool(cat.frame.apply_to_spaces),
    }

    body = {
        "board_spaces": {
            "layout": {
                row_id: row.model_dump() for row_id, row in cat.board_spaces.layout.items()
            },
        },
    }
    return columns, body


def _replace_cells(session, board_id: str, cat: Catalog) -> None:
    """Reconcile cells for ``board_id`` against ``cat``.

    Preserves ``cells.id`` for cells whose ``(kind, slug)`` natural key is
    unchanged, so ``asset_versions.cell_id`` survives a board edit. Cells
    no longer present in the catalog are deleted (and ``ON DELETE CASCADE``
    cleans up their history rows).
    """
    existing = session.scalars(
        select(CellRecord).where(CellRecord.board_uuid == board_id)
    ).all()
    by_natural_key: dict[tuple[str, str], CellRecord] = {
        (c.kind, c.slug): c for c in existing
    }

    desired_keys: set[tuple[str, str]] = set()

    for idx, design in enumerate(cat.board_spaces.designs):
        key = ("space", design.id)
        desired_keys.add(key)
        existing_row = by_natural_key.get(key)
        if existing_row is None:
            session.add(CellRecord(
                board_uuid=board_id,
                kind="space",
                slug=design.id,
                position_index=idx,
                prompt=design.prompt,
                space_kind=design.space_kind,
                positions_json=list(design.positions),
            ))
        else:
            existing_row.position_index = idx
            existing_row.prompt = design.prompt
            existing_row.space_kind = design.space_kind
            existing_row.positions_json = list(design.positions)

    for idx, panel in enumerate(cat.feature_panels.panels):
        key = ("panel", panel.id)
        desired_keys.add(key)
        existing_row = by_natural_key.get(key)
        bx1, by1, bx2, by2 = panel.bbox
        tw, th = panel.target_size
        if existing_row is None:
            session.add(CellRecord(
                board_uuid=board_id,
                kind="panel",
                slug=panel.id,
                position_index=idx,
                prompt=panel.prompt,
                needs_active=bool(panel.needs_active),
                active_kind=panel.active_kind,
                bbox_x1=int(bx1), bbox_y1=int(by1),
                bbox_x2=int(bx2), bbox_y2=int(by2),
                target_w=int(tw), target_h=int(th),
            ))
        else:
            existing_row.position_index = idx
            existing_row.prompt = panel.prompt
            existing_row.needs_active = bool(panel.needs_active)
            existing_row.active_kind = panel.active_kind
            existing_row.bbox_x1, existing_row.bbox_y1 = int(bx1), int(by1)
            existing_row.bbox_x2, existing_row.bbox_y2 = int(bx2), int(by2)
            existing_row.target_w, existing_row.target_h = int(tw), int(th)

    cp = cat.centerpiece
    cp_key = ("centerpiece", "centerpiece")
    desired_keys.add(cp_key)
    cp_row = by_natural_key.get(cp_key)
    bx1, by1, bx2, by2 = cp.bbox
    tw, th = cp.target_size
    if cp_row is None:
        session.add(CellRecord(
            board_uuid=board_id,
            kind="centerpiece",
            slug="centerpiece",
            position_index=0,
            prompt=cp.prompt,
            needs_active=bool(cp.needs_active),
            active_kind=cp.active_kind,
            bbox_x1=int(bx1), bbox_y1=int(by1),
            bbox_x2=int(bx2), bbox_y2=int(by2),
            target_w=int(tw), target_h=int(th),
        ))
    else:
        cp_row.prompt = cp.prompt
        cp_row.needs_active = bool(cp.needs_active)
        cp_row.active_kind = cp.active_kind
        cp_row.bbox_x1, cp_row.bbox_y1 = int(bx1), int(by1)
        cp_row.bbox_x2, cp_row.bbox_y2 = int(bx2), int(by2)
        cp_row.target_w, cp_row.target_h = int(tw), int(th)

    stale = [c for k, c in by_natural_key.items() if k not in desired_keys]
    for c in stale:
        session.delete(c)


# ────────────────────────── catalog public API ──────────────────────────


def load_catalog_dict(board_id: str) -> dict[str, Any] | None:
    """Return a dict suitable for ``Catalog.model_validate``, or ``None``."""
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None:
            return None
        cells = session.scalars(
            select(CellRecord).where(CellRecord.board_uuid == board_id)
        ).all()
        nested = _row_to_catalog_dict(row, cells)
        return Catalog.model_validate(nested).model_dump(mode="python")


def persist_catalog_dict(board_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate ``data`` as a ``Catalog`` and persist columns + body_json + cells."""
    cat = Catalog.model_validate(data)
    columns, body = _split_catalog(cat)
    stamp = _now_ms()

    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None:
            row = BoardGameRecord(
                board_uuid=board_id,
                body_json=body,
                updated_ms=stamp,
                **columns,
            )
            session.add(row)
        else:
            row.body_json = body
            row.updated_ms = stamp
            for k, v in columns.items():
                setattr(row, k, v)
        # Flush so the FK target exists before cells reference board_uuid.
        session.flush()
        _replace_cells(session, board_id, cat)

    return cat.model_dump(mode="python")


def load_catalog_model(board_id: str) -> Catalog | None:
    with session_scope() as session:
        row = session.get(BoardGameRecord, board_id)
        if row is None:
            return None
        cells = session.scalars(
            select(CellRecord).where(CellRecord.board_uuid == board_id)
        ).all()
        return Catalog.model_validate(_row_to_catalog_dict(row, cells))


def safe_load_catalog(board_id: str) -> dict[str, Any] | None:
    """Return the catalog dict for ``board_id``, or ``None`` if no DB row exists."""
    return load_catalog_dict(board_id)


def load_catalog(board_id: str) -> dict[str, Any]:
    data = safe_load_catalog(board_id)
    if data is None:
        raise CatalogNotFound(board_id)
    return data


def save_catalog(board_id: str, data: dict[str, Any]) -> None:
    """Validate and persist the catalog to relational tables only."""
    persist_catalog_dict(board_id, data)


# ────────────────────────── generation block ──────────────────────────


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


def read_generation_block(board_id: str) -> dict:
    """Convenience: ``read_generation(load_catalog(board_id))`` with a
    ``CatalogNotFound`` if the catalog is missing.
    """
    return read_generation(load_catalog(board_id))


def write_generation(board_id: str, body: dict) -> dict:
    """Validate ``body`` and persist as the new ``generation`` block."""
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
    save_catalog(board_id, catalog)
    return new_block


# ────────────────────────── space design reassign (per layout ref) ────


def _workspace_rel_for_version(rel_path: str) -> str:
    if rel_path.startswith("workspace/"):
        return rel_path
    return f"workspace/{rel_path}"


class SpaceDesignReassignError(ValueError):
    """Invalid space position / design id change."""


def reassign_space_position(
    board_id: str,
    *,
    from_design_id: str,
    position_ref: str,
    to_design_id: str | None = None,
    new_design_id: str | None = None,
    asset_policy: str = "empty",
) -> dict[str, Any]:
    """Move one layout reference from ``from_design_id`` to another design or a new id.

    * **Adopt** (``to_design_id``): join an existing design — shared live asset.
    * **Fork** (``new_design_id``): new design; default ``asset_policy`` is ``empty``
      (catalog only). ``copy_live`` duplicates promoted image + index row.
    """
    if bool(to_design_id) == bool(new_design_id):
        raise SpaceDesignReassignError("Specify exactly one of to_design_id or new_design_id")
    if asset_policy not in ("copy_live", "empty"):
        raise SpaceDesignReassignError('asset_policy must be "copy_live" or "empty"')

    if new_design_id is not None and not bf_boards.is_valid_id(new_design_id):
        raise SpaceDesignReassignError(
            "new_design_id must start with a letter or digit and contain only "
            "lowercase letters, digits, underscores, and hyphens"
        )

    catalog_dict = load_catalog(board_id)
    bs_spaces = catalog_dict["board_spaces"]
    designs: list[dict[str, Any]] = list(bs_spaces["designs"])
    layout = bs_spaces["layout"]

    src = next((d for d in designs if d["id"] == from_design_id), None)
    if src is None:
        raise SpaceDesignReassignError(f"Unknown source design {from_design_id!r}")
    positions = list(src.get("positions") or [])
    if position_ref not in positions:
        raise SpaceDesignReassignError(
            f"Position {position_ref!r} is not part of design {from_design_id!r}"
        )

    store = bs.get_store()
    live_rel_from = fs_ws.live_rel("spaces", from_design_id)
    live_bytes: bytes | None = None
    if store.exists(board_id, live_rel_from):
        live_bytes = store.read_bytes(board_id, live_rel_from)

    source_live_av_id: int | None = None
    with session_scope() as session:
        cell_from = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "space",
                CellRecord.slug == from_design_id,
            )
        )
        if cell_from is not None:
            source_live_av_id = cell_from.live_asset_version_id

    src_hist_bytes: bytes | None = None
    src_hist_meta: str | None = None
    if source_live_av_id is not None:
        with session_scope() as session:
            av = session.get(AssetVersionRecord, source_live_av_id)
            if av is not None:
                src_hist_meta = av.meta_json
                wrel = _workspace_rel_for_version(av.rel_path)
                if store.exists(board_id, wrel):
                    src_hist_bytes = store.read_bytes(board_id, wrel)
        if src_hist_bytes is None and live_bytes is not None:
            src_hist_bytes = live_bytes

    used_ids = {d["id"] for d in designs}

    def assert_ref_unused_elsewhere() -> None:
        for d in designs:
            if d["id"] == from_design_id:
                continue
            if position_ref in (d.get("positions") or []):
                raise SpaceDesignReassignError(
                    f"Position {position_ref!r} already uses design {d['id']!r}"
                )

    assert_ref_unused_elsewhere()

    if to_design_id is not None:
        if to_design_id == from_design_id:
            raise SpaceDesignReassignError("to_design_id must differ from from_design_id")
        tgt = next((d for d in designs if d["id"] == to_design_id), None)
        if tgt is None:
            raise SpaceDesignReassignError(f"Unknown target design {to_design_id!r}")
        _xr, _yr, rw, rh = resolve_position(layout, position_ref)
        trefs = tgt.get("positions") or []
        if not trefs:
            raise SpaceDesignReassignError(f"Target design {to_design_id!r} has no positions")
        _xt, _yt, tw, th = resolve_position(layout, trefs[0])
        if (rw, rh) != (tw, th):
            raise SpaceDesignReassignError(
                f"Target design {to_design_id!r} uses tile size {tw}×{th}px but "
                f"{position_ref!r} is {rw}×{rh}px"
            )

        new_positions = [p for p in positions if p != position_ref]
        src["positions"] = new_positions
        tgt["positions"] = list(dict.fromkeys([*tgt.get("positions", []), position_ref]))
        bs_spaces["designs"] = [d for d in designs if d["positions"]]
        catalog_dict["board_spaces"] = bs_spaces
        persist_catalog_dict(board_id, catalog_dict)
        return {
            "catalog": load_catalog(board_id),
            "result": "adopt",
            "design_id": to_design_id,
        }

    assert new_design_id is not None
    if new_design_id in used_ids:
        raise SpaceDesignReassignError(f"Design id {new_design_id!r} already exists")
    if new_design_id == from_design_id:
        raise SpaceDesignReassignError("new_design_id must differ from from_design_id")

    new_positions = [p for p in positions if p != position_ref]
    src["positions"] = new_positions
    new_design: dict[str, Any] = {
        "id": new_design_id,
        "prompt": src.get("prompt", ""),
        "space_kind": src.get("space_kind") or "standard",
        "positions": [position_ref],
    }
    designs_after = [d for d in designs if d["positions"]]
    designs_after.append(new_design)
    bs_spaces["designs"] = designs_after
    catalog_dict["board_spaces"] = bs_spaces
    persist_catalog_dict(board_id, catalog_dict)

    if asset_policy == "copy_live":
        png = src_hist_bytes or live_bytes
        if png is not None:
            live_rel_to = fs_ws.live_rel("spaces", new_design_id)
            store.write_bytes(board_id, live_rel_to, png)
            ts_ms = int(time.time() * 1000)
            digest = hashlib.sha256(png).hexdigest()
            fork_bn = f"fork_{ts_ms}__001.png"
            rel_db = f"history/spaces/{new_design_id}/{fork_bn}"
            hist_store = f"workspace/{rel_db}"
            store.write_bytes(board_id, hist_store, png)
            meta_json = src_hist_meta
            if meta_json is None:
                meta_json = json.dumps(
                    {
                        "operation": "fork",
                        "prompt": new_design.get("prompt", ""),
                        "ts_ms": ts_ms,
                        "seq": 1,
                    }
                )
            with session_scope() as session:
                cell_new = session.scalar(
                    select(CellRecord).where(
                        CellRecord.board_uuid == board_id,
                        CellRecord.kind == "space",
                        CellRecord.slug == new_design_id,
                    )
                )
                if cell_new is not None:
                    av_row = AssetVersionRecord(
                        board_uuid=board_id,
                        cell_id=cell_new.id,
                        category="spaces",
                        asset_id=new_design_id,
                        basename=fork_bn,
                        rel_path=rel_db,
                        sha256=digest,
                        ts_ms=ts_ms,
                        meta_json=meta_json,
                    )
                    session.add(av_row)
                    session.flush()
                    cell_new.live_asset_version_id = av_row.id

    return {
        "catalog": load_catalog(board_id),
        "result": "fork",
        "design_id": new_design_id,
    }


# ────────────────────────── board summaries ──────────────────────────


# Compositor writes ``board_idle.png`` (and ``board_active.png``); older trees may
# have ``board_preview.png`` only — prefer idle first for list + preview page URLs.
COMPOSITE_PREVIEW_CANDIDATES: tuple[str, ...] = (
    "workspace/preview/board_idle.png",
    "workspace/preview/board_preview.png",
)


def composite_preview_workspace_rel(board_id: str) -> str | None:
    """First composited preview PNG on disk, or ``None``."""
    store = bs.get_store()
    for rel in COMPOSITE_PREVIEW_CANDIDATES:
        if store.exists(board_id, rel):
            return rel
    return None


def _mockup_thumb_name(board_id: str, catalog: dict | None) -> str | None:
    """Basename for ``/mockup/{name}`` when that file exists; else ``None``."""
    store = bs.get_store()
    rel = fs_ws.mockup_relpath(catalog)
    if not store.exists(board_id, rel):
        return None
    return Path(rel).name


@dataclass(frozen=True)
class BoardSummary:
    """UI-friendly view of a board.

    ``project`` is the catalog display name (from the DB row).
    ``has_catalog`` is true when a ``board_games`` row exists for this id —
    in normal operation this is always true for owned boards; it's only
    false during a brief inconsistency window if the row was deleted but
    ownership wasn't.
    ``has_palette`` / ``has_mockup`` reflect on-disk state at call time.
    ``has_board_preview`` is true when a composited preview PNG exists
    (``board_idle.png`` or legacy ``board_preview.png``).
    ``board_preview_asset_rest`` is the path under ``workspace/`` for the asset
    URL (e.g. ``preview/board_idle.png``).
    ``mockup_thumb_name`` is the mockup filename for list thumbnails when
    present (used when there is no board preview).
    """

    id: str
    project: str
    path_slug: str  # URL segment under board-games/ (per-user unique)
    has_catalog: bool
    has_mockup: bool
    has_palette: bool
    has_board_preview: bool
    board_preview_asset_rest: str | None
    mockup_thumb_name: str | None


def _board_info_for_list(board_id: str) -> bf_boards.BoardInfo:
    """Prefer on-disk ``BoardInfo``; if the directory is missing, synthesize
    a minimal one so owned boards still appear in the list (catalog metadata
    is fetched from the DB by the caller).
    """
    info = bf_boards.get_board(board_id)
    if info is not None:
        return info
    return bf_boards.BoardInfo(id=board_id, project=board_id, has_mockup=False)


def _summary(info: bf_boards.BoardInfo) -> BoardSummary:
    ps = boards_repo.path_slug_for_board(info.id) or info.id
    preview_ws_rel = composite_preview_workspace_rel(info.id)
    has_preview = preview_ws_rel is not None
    preview_asset_rest = (
        preview_ws_rel.removeprefix("workspace/") if preview_ws_rel else None
    )
    d = load_catalog_dict(info.id)
    mock_name = _mockup_thumb_name(info.id, d)
    project = str(d.get("project") or info.id) if d is not None else info.project
    return BoardSummary(
        id=info.id,
        project=project,
        path_slug=ps,
        has_catalog=d is not None,
        has_mockup=info.has_mockup,
        has_palette=fs_ws.has_palette(info.id),
        has_board_preview=has_preview,
        board_preview_asset_rest=preview_asset_rest,
        mockup_thumb_name=mock_name,
    )


def _board_last_activity_ms(board_ids: list[str]) -> dict[str, int]:
    """Map ``board_id`` -> last-activity time for list ordering.

    Uses the later of ``board_games.updated_ms`` (catalog ``body_json`` saved)
    and ``style_lock_updated_ms`` (style-lock palette written to the row),
    in milliseconds. Boards with no row sort as 0 (last).
    """
    if not board_ids:
        return {}
    out: dict[str, int] = {}
    with session_scope() as session:
        for bid in board_ids:
            row = session.get(BoardGameRecord, bid)
            if row is None:
                out[bid] = 0
                continue
            cat = int(row.updated_ms)
            pal = int(row.style_lock_updated_ms) if row.style_lock_updated_ms is not None else 0
            out[bid] = max(cat, pal)
    return out


# ────────────────────────── board CRUD ──────────────────────────


def list_boards(user_id: str) -> list[BoardSummary]:
    bids = boards_repo.list_board_ids_for_user(user_id)
    if not bids:
        return []
    updated_ms = _board_last_activity_ms(bids)
    summaries = [_summary(_board_info_for_list(bid)) for bid in bids]
    summaries.sort(key=lambda s: (-updated_ms.get(s.id, 0), s.id))
    return summaries


def default_board_id_for_user(user_id: str) -> str | None:
    """If this user owns exactly one board, return its id (for legacy redirects)."""
    rows = list_boards(user_id)
    if len(rows) == 1:
        return rows[0].id
    return None


def get_board(user_id: str, board_id: str) -> BoardSummary:
    if not bf_boards.is_board_uuid(board_id):
        raise InvalidBoardId(board_id)
    if not boards_repo.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)
    info = bf_boards.get_board(board_id)
    if info is None:
        raise BoardNotFound(board_id)
    return _summary(info)


def create_board(
    path_slug: str,
    *,
    owner_user_id: str,
    project_name: str | None = None,
) -> BoardSummary:
    """Create a new empty board and record ``owner_user_id`` as its owner."""
    boards_repo.require_nonblank_user_id(owner_user_id, field="owner_user_id")
    slug = bf_boards.slugify(path_slug)
    if not bf_boards.is_valid_id(slug):
        raise InvalidBoardId(slug)
    if boards_repo.path_slug_in_use(owner_user_id, slug):
        raise BoardExists(slug)
    bu = str(uuid.uuid4())
    pname = project_name or slug
    persist_catalog_dict(bu, bf_boards.default_catalog_dict(bu, pname))
    boards_repo.link_board_to_user(bu, owner_user_id, path_slug=slug)
    bs.get_store().create_board_skeleton(bu)
    info = bf_boards.get_board(bu)
    if info is None:
        raise BoardNotFound(bu)
    return _summary(info)


def clone_board(
    user_id: str,
    source_board_id: str,
    *,
    path_slug: str | None = None,
    project_name: str | None = None,
) -> BoardSummary:
    """Duplicate on-disk files plus ``board_games``, ``owned_boards``, ``cells``, and
    ``asset_versions`` for the same owner. Returns the new board summary.

    The clone receives a new UUID directory under the owner's boards tree and a
    fresh ``path_slug`` (default ``copy-of-<source-slug>-N``). Unless
    ``project_name`` is passed, the display title is ``"{original project} (copy)"``.
    """
    boards_repo.require_nonblank_user_id(user_id, field="user_id")
    if not bf_boards.is_board_uuid(source_board_id):
        raise InvalidBoardId(source_board_id)
    if not boards_repo.user_owns_board(user_id, source_board_id):
        raise BoardNotFound(source_board_id)

    new_uuid = str(uuid.uuid4())
    src_root = boards_repo.store_board_root(source_board_id)
    if not src_root.is_dir():
        raise BoardNotFound(source_board_id)

    dst_root = boards_repo.user_board_root(user_id, new_uuid)

    def _pick_slug() -> str:
        if path_slug is not None:
            s = bf_boards.slugify(path_slug)
            if not bf_boards.is_valid_id(s):
                raise InvalidBoardId(s)
            if boards_repo.path_slug_in_use(user_id, s):
                raise BoardExists(s)
            return s
        src_slug = boards_repo.path_slug_for_board(source_board_id) or "board"
        base = bf_boards.slugify(f"copy-of-{src_slug}")
        candidate = base
        n = 2
        while boards_repo.path_slug_in_use(user_id, candidate):
            candidate = bf_boards.slugify(f"{base}-{n}")
            n += 1
        return candidate

    slug = _pick_slug()

    if dst_root.exists():
        shutil.rmtree(dst_root)
    try:
        shutil.copytree(src_root, dst_root)
    except Exception:
        if dst_root.exists():
            shutil.rmtree(dst_root, ignore_errors=True)
        raise

    try:
        _clone_board_relational(
            user_id=user_id,
            source_board_id=source_board_id,
            new_uuid=new_uuid,
            path_slug=slug,
            project_name=project_name,
        )
    except Exception:
        shutil.rmtree(dst_root, ignore_errors=True)
        raise

    info = bf_boards.get_board(new_uuid)
    if info is None:
        raise BoardNotFound(new_uuid)
    return _summary(info)


def _clone_board_relational(
    *,
    user_id: str,
    source_board_id: str,
    new_uuid: str,
    path_slug: str,
    project_name: str | None,
) -> None:
    with session_scope() as session:
        src_bg = session.get(BoardGameRecord, source_board_id)
        if src_bg is None:
            raise BoardNotFound(source_board_id)
        src_ob = session.get(OwnedBoardRecord, source_board_id)

        title = (project_name or "").strip() or f"{src_bg.project} (copy)"
        stamp = _now_ms()

        session.add(
            BoardGameRecord(
                board_uuid=new_uuid,
                project=title,
                board_size_w=src_bg.board_size_w,
                board_size_h=src_bg.board_size_h,
                style_reference_image=src_bg.style_reference_image,
                style_prompt=src_bg.style_prompt,
                palette_size=src_bg.palette_size,
                provider=src_bg.provider,
                openai_model=src_bg.openai_model,
                openai_quality=src_bg.openai_quality,
                pixellab_model=src_bg.pixellab_model,
                generation_configured=src_bg.generation_configured,
                frame_enabled=src_bg.frame_enabled,
                frame_apply_to_panels=src_bg.frame_apply_to_panels,
                frame_apply_to_spaces=src_bg.frame_apply_to_spaces,
                body_json=dict(src_bg.body_json or {}),
                updated_ms=stamp,
                palette_json=src_bg.palette_json,
                palette_gpl_text=src_bg.palette_gpl_text,
                style_lock_updated_ms=src_bg.style_lock_updated_ms,
            )
        )
        session.add(
            OwnedBoardRecord(
                board_uuid=new_uuid,
                user_id=user_id,
                path_slug=path_slug,
                created_ms=stamp,
                list_order=src_ob.list_order if src_ob is not None else 0,
            )
        )
        session.flush()

        cells_src = session.scalars(
            select(CellRecord).where(CellRecord.board_uuid == source_board_id)
        ).all()
        cell_map: dict[str, str] = {}
        for c in cells_src:
            nid = str(uuid.uuid4())
            cell_map[str(c.id)] = nid
            if c.kind == "space":
                session.add(
                    CellRecord(
                        id=nid,
                        board_uuid=new_uuid,
                        kind=c.kind,
                        slug=c.slug,
                        position_index=c.position_index,
                        prompt=c.prompt,
                        needs_active=c.needs_active,
                        active_kind=c.active_kind,
                        space_kind=c.space_kind,
                        positions_json=c.positions_json,
                    )
                )
            else:
                # Match ``_replace_cells``: omit space-only JSON columns so Postgres
                # gets SQL NULL (not JSON null) for ``positions_json``.
                session.add(
                    CellRecord(
                        id=nid,
                        board_uuid=new_uuid,
                        kind=c.kind,
                        slug=c.slug,
                        position_index=c.position_index,
                        prompt=c.prompt,
                        needs_active=c.needs_active,
                        active_kind=c.active_kind,
                        bbox_x1=c.bbox_x1,
                        bbox_y1=c.bbox_y1,
                        bbox_x2=c.bbox_x2,
                        bbox_y2=c.bbox_y2,
                        target_w=c.target_w,
                        target_h=c.target_h,
                        live_asset_version_id=None,
                    )
                )
        session.flush()

        av_src = session.scalars(
            select(AssetVersionRecord)
            .where(AssetVersionRecord.board_uuid == source_board_id)
            .order_by(AssetVersionRecord.id)
        ).all()
        pending: list[tuple[int, AssetVersionRecord]] = []
        for av in av_src:
            nav = AssetVersionRecord(
                board_uuid=new_uuid,
                cell_id=cell_map[str(av.cell_id)],
                category=av.category,
                asset_id=av.asset_id,
                basename=av.basename,
                rel_path=av.rel_path,
                sha256=av.sha256,
                ts_ms=av.ts_ms,
                meta_json=av.meta_json,
            )
            session.add(nav)
            pending.append((av.id, nav))
        session.flush()
        av_map = {old_id: nav.id for old_id, nav in pending}

        for c in cells_src:
            old_live = c.live_asset_version_id
            if old_live is None or old_live not in av_map:
                continue
            nc = session.get(CellRecord, cell_map[str(c.id)])
            if nc is not None:
                nc.live_asset_version_id = av_map[old_live]


def delete_board(user_id: str, board_id: str) -> None:
    """Remove a board's relational rows (spec, asset index, ownership) and
    delete its data tree from the configured ``BoardStore``.
    """
    if not bf_boards.is_board_uuid(board_id):
        raise InvalidBoardId(board_id)
    if not boards_repo.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)

    bs.get_store().delete_board(board_id)

    with session_scope() as session:
        session.execute(
            delete(AssetVersionRecord).where(AssetVersionRecord.board_uuid == board_id)
        )
        session.execute(delete(OwnedBoardRecord).where(OwnedBoardRecord.board_uuid == board_id))
        session.execute(delete(BoardGameRecord).where(BoardGameRecord.board_uuid == board_id))


def rename_board(user_id: str, board_id: str, project_name: str) -> BoardSummary:
    """Update the display name (catalog.project)."""
    if not bf_boards.is_board_uuid(board_id):
        raise InvalidBoardId(board_id)
    if not boards_repo.user_owns_board(user_id, board_id):
        raise BoardNotFound(board_id)
    new_name = (project_name or "").strip()
    if not new_name:
        raise ValueError("Project name cannot be empty")
    data = load_catalog(board_id)
    data["project"] = new_name
    save_catalog(board_id, data)
    info = bf_boards.get_board(board_id)
    if info is None:
        raise BoardNotFound(board_id)
    return _summary(info)


def mockup_present(board_id: str) -> tuple[bool, str]:
    """Return ``(exists, board-relative-path)`` for templates."""
    catalog = safe_load_catalog(board_id)
    if catalog is None:
        return (False, "mockup/board.png")
    rel = fs_ws.mockup_relpath(catalog)
    return (bs.get_store().exists(board_id, rel), rel)

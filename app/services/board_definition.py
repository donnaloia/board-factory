"""Relational board definition ↔ pipeline ``Catalog`` shape.

The pipeline consumes a nested dict / ``Catalog`` model; the database stores a
normalized ``board_games`` row plus child tables. This module is the single
adapter between those representations.

``board_catalogs.body_json`` is updated on every persist as a transitional mirror
for code that still expects one JSON blob.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from boardfactory.schemas import Catalog

from storage.db import session_scope
from storage.models.core import (
    BoardCatalogRecord,
    BoardFeaturePanelRecord,
    BoardGameRecord,
    BoardSpaceDesignRecord,
    BoardSpaceLayoutRowRecord,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _legacy_mirror(session: Session, board_id: str, body: dict[str, Any]) -> None:
    blob = json.dumps(body, ensure_ascii=False)
    stamp = _now_ms()
    row = session.get(BoardCatalogRecord, board_id)
    if row is None:
        session.add(BoardCatalogRecord(board_id=board_id, body_json=blob, updated_ms=stamp))
    else:
        row.body_json = blob
        row.updated_ms = stamp


def load_catalog_dict(board_id: str) -> dict[str, Any] | None:
    """Return a dict suitable for ``Catalog.model_validate``, or ``None``."""
    with session_scope() as session:
        bg = session.get(BoardGameRecord, board_id)
        if bg is None:
            return None

        layout_rows = session.scalars(
            select(BoardSpaceLayoutRowRecord)
            .where(BoardSpaceLayoutRowRecord.board_id == board_id)
            .order_by(BoardSpaceLayoutRowRecord.sort_order, BoardSpaceLayoutRowRecord.id)
        ).all()
        designs = session.scalars(
            select(BoardSpaceDesignRecord)
            .where(BoardSpaceDesignRecord.board_id == board_id)
            .order_by(BoardSpaceDesignRecord.sort_order, BoardSpaceDesignRecord.id)
        ).all()
        panels = session.scalars(
            select(BoardFeaturePanelRecord)
            .where(BoardFeaturePanelRecord.board_id == board_id)
            .order_by(BoardFeaturePanelRecord.sort_order, BoardFeaturePanelRecord.id)
        ).all()

        layout: dict[str, Any] = {}
        for lr in layout_rows:
            layout[lr.row_key] = {
                "count": lr.count,
                "start": [lr.start_x, lr.start_y],
                "spacing": lr.spacing,
                "axis": lr.axis,
                "size": [lr.size_w, lr.size_h],
            }

        design_list = []
        for d in designs:
            design_list.append(
                {
                    "id": d.design_id,
                    "prompt": d.prompt,
                    "space_kind": d.space_kind,
                    "positions": json.loads(d.positions_json),
                }
            )

        panel_list = []
        for p in panels:
            panel_list.append(
                {
                    "id": p.panel_id,
                    "bbox": [p.bbox_x1, p.bbox_y1, p.bbox_x2, p.bbox_y2],
                    "target_size": [p.target_w, p.target_h],
                    "prompt": p.prompt,
                    "needs_active": p.needs_active,
                    "active_kind": p.active_kind,
                }
            )

        generation = json.loads(bg.generation_json)
        frame = json.loads(bg.frame_json)

        body: dict[str, Any] = {
            "project": bg.project,
            "board_size": [bg.board_size_w, bg.board_size_h],
            "style": {
                "reference_image": bg.style_reference_image,
                "palette_size": int(generation.get("palette_size", 36)),
                "prompt": bg.style_prompt,
            },
            "centerpiece": {
                "bbox": [bg.cp_bbox_x1, bg.cp_bbox_y1, bg.cp_bbox_x2, bg.cp_bbox_y2],
                "target_size": [bg.cp_target_w, bg.cp_target_h],
                "prompt": bg.cp_prompt,
                "needs_active": bg.cp_needs_active,
                "active_kind": bg.cp_active_kind,
            },
            "board_spaces": {"layout": layout, "designs": design_list},
            "feature_panels": {"panels": panel_list},
            "frame": frame,
            "generation": generation,
        }
        return body


def persist_catalog_dict(board_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate ``data`` as a ``Catalog``, persist relational + legacy mirror.

    Returns the validated model as a dict (JSON-friendly).
    """
    cat = Catalog.model_validate(data)
    stamp = _now_ms()
    dumped = cat.model_dump(mode="python")

    with session_scope() as session:
        prev = session.get(BoardGameRecord, board_id)
        keep_palette_json = prev.palette_json if prev else None
        keep_palette_gpl = prev.palette_gpl_text if prev else None
        keep_style_ms = prev.style_lock_updated_ms if prev else None

        session.execute(delete(BoardGameRecord).where(BoardGameRecord.board_id == board_id))

        gen = cat.generation.model_dump(mode="python")
        frm = cat.frame.model_dump(mode="python")

        session.add(
            BoardGameRecord(
                board_id=board_id,
                project=cat.project,
                board_size_w=int(cat.board_size[0]),
                board_size_h=int(cat.board_size[1]),
                style_reference_image=cat.style.reference_image,
                style_prompt=cat.style.prompt,
                cp_bbox_x1=int(cat.centerpiece.bbox[0]),
                cp_bbox_y1=int(cat.centerpiece.bbox[1]),
                cp_bbox_x2=int(cat.centerpiece.bbox[2]),
                cp_bbox_y2=int(cat.centerpiece.bbox[3]),
                cp_target_w=int(cat.centerpiece.target_size[0]),
                cp_target_h=int(cat.centerpiece.target_size[1]),
                cp_prompt=cat.centerpiece.prompt,
                cp_needs_active=bool(cat.centerpiece.needs_active),
                cp_active_kind=str(cat.centerpiece.active_kind),
                generation_json=json.dumps(gen, ensure_ascii=False),
                frame_json=json.dumps(frm, ensure_ascii=False),
                updated_ms=stamp,
                palette_json=keep_palette_json,
                palette_gpl_text=keep_palette_gpl,
                style_lock_updated_ms=keep_style_ms,
            )
        )
        session.flush()

        for i, (row_key, row) in enumerate(cat.board_spaces.layout.items()):
            session.add(
                BoardSpaceLayoutRowRecord(
                    board_id=board_id,
                    sort_order=i,
                    row_key=row_key,
                    count=int(row.count),
                    start_x=int(row.start[0]),
                    start_y=int(row.start[1]),
                    spacing=int(row.spacing),
                    axis=str(row.axis),
                    size_w=int(row.size[0]),
                    size_h=int(row.size[1]),
                )
            )

        for i, d in enumerate(cat.board_spaces.designs):
            session.add(
                BoardSpaceDesignRecord(
                    board_id=board_id,
                    sort_order=i,
                    design_id=d.id,
                    prompt=d.prompt,
                    space_kind=str(d.space_kind),
                    positions_json=json.dumps(list(d.positions), ensure_ascii=False),
                )
            )

        for i, p in enumerate(cat.feature_panels.panels):
            session.add(
                BoardFeaturePanelRecord(
                    board_id=board_id,
                    sort_order=i,
                    panel_id=p.id,
                    bbox_x1=int(p.bbox[0]),
                    bbox_y1=int(p.bbox[1]),
                    bbox_x2=int(p.bbox[2]),
                    bbox_y2=int(p.bbox[3]),
                    target_w=int(p.target_size[0]),
                    target_h=int(p.target_size[1]),
                    prompt=p.prompt,
                    needs_active=bool(p.needs_active),
                    active_kind=str(p.active_kind),
                )
            )

        _legacy_mirror(session, board_id, dumped)

    return dumped


def load_catalog_model(board_id: str) -> Catalog | None:
    d = load_catalog_dict(board_id)
    if d is None:
        return None
    return Catalog.model_validate(d)

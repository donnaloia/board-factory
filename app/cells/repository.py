"""DB I/O for ``cells`` rows.

Pure data layer: opens its own ``session_scope``, never touches HTTP or
Catalog (Pydantic). Callers are domain services that need cell-level
queries that ``board_definition`` doesn't already serve via the catalog
reassembly path.

If you find yourself querying ``cells`` directly from a route or another
domain, route the call through ``cells.services`` instead.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select

from infrastructure.db import session_scope
from models.core import CellRecord


# ────────────────────────── id translation ──────────────────────────


_CATEGORY_TO_KIND = {"spaces": "space", "panels": "panel", "centerpiece": "centerpiece"}
_KIND_TO_CATEGORY = {v: k for k, v in _CATEGORY_TO_KIND.items()}


def category_to_kind(category: str) -> str | None:
    """Map the legacy ``"spaces"|"panels"|"centerpiece"`` string used on
    URLs and the filesystem to the ``cells.kind`` enum value."""
    return _CATEGORY_TO_KIND.get(category)


def kind_to_category(kind: str) -> str | None:
    return _KIND_TO_CATEGORY.get(kind)


# ────────────────────────── reads ──────────────────────────


def find_id(board_id: str, category: str, slug: str) -> str | None:
    """Return ``cells.id`` for a (board, category, slug) triple, or None."""
    kind = category_to_kind(category)
    if kind is None:
        return None
    with session_scope() as session:
        return session.scalar(
            select(CellRecord.id).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )


def list_for_board(board_id: str) -> list[CellRecord]:
    with session_scope() as session:
        return list(session.scalars(
            select(CellRecord)
            .where(CellRecord.board_uuid == board_id)
            .order_by(CellRecord.kind, CellRecord.position_index)
        ))


def list_kind_slugs(board_id: str, kind: str) -> list[str]:
    """Just the slugs for one kind, sorted by ``position_index``."""
    with session_scope() as session:
        return list(session.scalars(
            select(CellRecord.slug)
            .where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
            )
            .order_by(CellRecord.position_index)
        ))


# ────────────────────────── focused mutators ──────────────────────────


def update_prompt(board_id: str, category: str, slug: str, prompt: str) -> bool:
    """Patch one cell's prompt. Returns True on success, False if not found."""
    kind = category_to_kind(category)
    if kind is None:
        return False
    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == kind,
                CellRecord.slug == slug,
            )
        )
        if row is None:
            return False
        row.prompt = prompt
        return True


def update_space_kind(board_id: str, slug: str, space_kind: str) -> bool:
    """Patch a space cell's ``space_kind`` (``standard`` | ``event``)."""
    if space_kind not in ("standard", "event"):
        raise ValueError(f"invalid space_kind: {space_kind!r}")
    with session_scope() as session:
        row = session.scalar(
            select(CellRecord).where(
                CellRecord.board_uuid == board_id,
                CellRecord.kind == "space",
                CellRecord.slug == slug,
            )
        )
        if row is None:
            return False
        row.space_kind = space_kind
        return True

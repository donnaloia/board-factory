"""Shared FastAPI dependencies for nested board URL surfaces."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from infrastructure import deps

NestedBoardId = Annotated[str, Depends(deps.require_nested_board)]


def board_prefix(board_id: str) -> str:
    return deps.board_http_prefix(board_id)

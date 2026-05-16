"""Disk-side helpers for the per-job proposal manifest + workspace layout.

Pure functions. The pipeline writes the manifest and candidate files; this
slice owns reading them back and computing the canonical paths under each
board's workspace.

Layout (per board, per cell):

    workspace/animations/<cell_id>/
      _proposals/<job_id>/
        manifest.json
        0.gif | 0.apng           # produced by pipeline
        1.gif | 1.apng
        2.gif | 2.apng
      live.gif | live.apng       # the currently committed clip
      history/
        <created_ms>__<basename>  # archived previous live clips
"""

from __future__ import annotations

import json
from pathlib import Path

from space_animations.schemas.manifest import ProposalManifest

from infrastructure.files import workspace as fs_ws


# ────────────────────────── path helpers ──────────────────────────


def animations_root(board_id: str, cell_id: str) -> Path:
    """``<workspace>/animations/<cell_id>/`` for one cell. Local-only."""
    return fs_ws.workspace_dir(board_id) / "animations" / cell_id


def proposal_dir(board_id: str, cell_id: str, job_id: str) -> Path:
    return animations_root(board_id, cell_id) / "_proposals" / job_id


def proposal_file(board_id: str, cell_id: str, job_id: str, filename: str) -> Path:
    return proposal_dir(board_id, cell_id, job_id) / filename


def manifest_path(board_id: str, cell_id: str, job_id: str) -> Path:
    return proposal_dir(board_id, cell_id, job_id) / "manifest.json"


def live_path(board_id: str, cell_id: str, encoding: str) -> Path:
    return animations_root(board_id, cell_id) / f"live.{_ext(encoding)}"


def history_dir(board_id: str, cell_id: str) -> Path:
    return animations_root(board_id, cell_id) / "history"


def history_path(
    board_id: str,
    cell_id: str,
    *,
    created_ms: int,
    basename: str,
) -> Path:
    return history_dir(board_id, cell_id) / f"{created_ms}__{basename}"


# ────────────────────────── workspace-relative paths (BoardStore) ──────────────────────────


def proposal_rel(cell_id: str, job_id: str, filename: str) -> str:
    return f"workspace/animations/{cell_id}/_proposals/{job_id}/{filename}"


def manifest_rel(cell_id: str, job_id: str) -> str:
    return proposal_rel(cell_id, job_id, "manifest.json")


def live_rel(cell_id: str, encoding: str) -> str:
    return f"workspace/animations/{cell_id}/live.{_ext(encoding)}"


def history_rel(cell_id: str, *, created_ms: int, basename: str) -> str:
    return f"workspace/animations/{cell_id}/history/{created_ms}__{basename}"


# ────────────────────────── manifest reads ──────────────────────────


def read_manifest(board_id: str, cell_id: str, job_id: str) -> ProposalManifest | None:
    """Return the parsed manifest for one job, or ``None`` if absent."""
    path = manifest_path(board_id, cell_id, job_id)
    if not path.exists():
        return None
    return ProposalManifest.model_validate_json(path.read_text())


def _ext(encoding: str) -> str:
    e = (encoding or "").strip().lower()
    if e == "apng":
        return "apng"
    return "gif"

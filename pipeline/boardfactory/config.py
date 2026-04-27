"""Workspace paths and configuration constants.

Every path is computed once at import time from BOARDFACTORY_REPO so the rest
of the pipeline can use plain `from boardfactory.config import WORKSPACE` etc.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))

CATALOG_PATH = REPO_ROOT / "catalog" / "board.yml"
MOCKUP_DIR = REPO_ROOT / "mockup"

WORKSPACE = REPO_ROOT / "workspace"
STYLE_DIR = WORKSPACE / "style"
CANDIDATES_DIR = WORKSPACE / "candidates"
CLEANED_DIR = WORKSPACE / "cleaned"
APPROVED_DIR = WORKSPACE / "approved"
REFINEMENTS_DIR = WORKSPACE / "refinements"
PREVIEW_DIR = WORKSPACE / "preview"
LOGS_DIR = WORKSPACE / "logs"

EXPORT_DIR = REPO_ROOT / "board_assets"

# Pipeline knobs (overridable via env)
PALETTE_SIZE = int(os.environ.get("BOARDFACTORY_PALETTE_SIZE", "24"))
SPACE_CANDIDATES = int(os.environ.get("BOARDFACTORY_SPACE_CANDIDATES", "3"))
PANEL_CANDIDATES = int(os.environ.get("BOARDFACTORY_PANEL_CANDIDATES", "6"))
CENTERPIECE_CANDIDATES = int(os.environ.get("BOARDFACTORY_CENTERPIECE_CANDIDATES", "12"))

PROJECT_NAME = os.environ.get("BOARDFACTORY_PROJECT_NAME", "my-board")
PROVIDER_NAME = os.environ.get("BOARDFACTORY_PROVIDER", "pixellab").lower()


def ensure_dirs() -> None:
    for d in [
        STYLE_DIR, CANDIDATES_DIR, CLEANED_DIR, APPROVED_DIR,
        REFINEMENTS_DIR, PREVIEW_DIR, LOGS_DIR, EXPORT_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)

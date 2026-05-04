"""Record which history PNG was last promoted to ``workspace/live/``.

The side panel's ``active_prompt`` must match the **explicit** promotion choice,
not just byte-equality (duplicate pixels, cleanup rows with missing metadata).

Writes one JSON file per cell under ``workspace/meta/live_source/`` — see
``record_promoted_history_file``. The web app reads the same path via
``BoardStore`` (``storage.fs.workspace.live_source_rel``).

Schema version 1::

    {
      "schema": 1,
      "history_filename": "1735012345__001.png",
      "recorded_ms": 1735012400000
    }
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

SCHEMA_VERSION = 1


def live_source_json_path(category: str, asset_id: str) -> Path:
    """Local path to the promotion pointer for one cell (pipeline / tests)."""
    return (
        config.WORKSPACE
        / "meta"
        / "live_source"
        / category
        / f"{asset_id}.json"
    )


def record_promoted_history_file(
    category: str, asset_id: str, history_filename: str,
) -> Path:
    """Persist which history basename is now live; called from ``promote()``."""
    path = live_source_json_path(category, asset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA_VERSION,
        "history_filename": history_filename,
        "recorded_ms": int(time.time() * 1000),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path

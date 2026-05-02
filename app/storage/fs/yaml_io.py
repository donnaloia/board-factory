"""YAML read / atomic-write helpers.

The whole codebase loads and saves YAML in a few different shapes; we
funnel all of them through this module so:

* Atomic writes use a tmp file + ``os.replace`` everywhere (no partial
  catalog after a crash).
* Dump options (``sort_keys=False``) are fixed in one place so the
  on-disk representation stays git-diff stable.
* Reads return ``None`` for missing files so callers don't have to
  ``Path.exists()`` ahead of every load.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict | None:
    """Return the YAML at ``path`` as a dict, or ``None`` if the file is missing."""
    if not path.exists():
        return None
    with path.open() as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else None


def save_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` via a tmp file + ``os.replace``.

    ``sort_keys=False`` keeps the field order the dict was authored with,
    which matters for git diffs of catalog.yml.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp, path)

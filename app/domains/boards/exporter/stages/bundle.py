"""Stage 3 — persist ``project.json`` at the bundle root (§9.2)."""

from __future__ import annotations

import json

from domains.boards.exporter.state import BoardExportState


def stage_write_project_json(state: BoardExportState) -> None:
    """Write ``state.project`` to ``bundle_root / project_json_basename``.

    Skips when ``bundle_root`` is ``None`` (in-memory export only). Creates
    ``bundle_root`` when missing. Zip / compression is **not** handled here.
    """
    root = state.options.bundle_root
    if root is None:
        return
    name = (state.options.project_json_basename or "project.json").strip()
    if not name or "/" in name or "\\" in name or name.startswith(".."):
        state.errors.append(f"bundle: invalid project_json_basename: {name!r}")
        return
    path = root / name
    try:
        root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(state.project, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        state.errors.append(f"bundle: write {path}: {e}")

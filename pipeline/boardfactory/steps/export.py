"""Export live assets + manifest under ``<store-root>/<id>/export/`` for engine use.

Outputs three things:

  1. Tile PNGs organized by category under ``export/{centerpiece,panels,spaces}/``
  2. ``board_manifest.json`` mapping tile_id -> file path + position + animation
  3. The composited preview as a reference asset (under ``export/preview/``)

Reads from resolved live paths only. Anything not promoted as live is
intentionally not included in the export bundle.
"""

from __future__ import annotations

import json
import shutil

from .. import assets, config
from ..ops.progress import ProgressSink
from ..schemas import Catalog


def do_export(catalog: Catalog, sink: ProgressSink) -> None:
    manifest: dict = {
        "project": catalog.project,
        "board_size": list(catalog.board_size),
        "centerpiece": None,
        "feature_panels": [],
        "board_spaces": [],
    }

    files_to_copy: list[tuple] = []  # (src, dst)
    failures: list[str] = []

    # Centerpiece.
    cp_src = assets.live_path("centerpiece", "centerpiece")
    if cp_src.exists():
        cp_dst = config.EXPORT_DIR / "centerpiece" / "centerpiece.png"
        files_to_copy.append((cp_src, cp_dst))
        cp_active = config.LIVE_DIR / "centerpiece" / "centerpiece_active.png"
        if cp_active.exists():
            files_to_copy.append(
                (cp_active, config.EXPORT_DIR / "centerpiece" / "centerpiece_active.png")
            )
        manifest["centerpiece"] = {
            "id": "centerpiece",
            "file": "centerpiece/centerpiece.png",
            "active_file": (
                "centerpiece/centerpiece_active.png" if cp_active.exists() else None
            ),
            "bbox": list(catalog.centerpiece.bbox),
            "target_size": list(catalog.centerpiece.target_size),
            "active_kind": catalog.centerpiece.active_kind,
        }
    else:
        failures.append("centerpiece")

    # Feature panels.
    for panel in catalog.all_panels():
        src = assets.live_path("panels", panel.id)
        if not src.exists():
            failures.append(f"panel:{panel.id}")
            continue
        dst = config.EXPORT_DIR / "panels" / f"{panel.id}.png"
        files_to_copy.append((src, dst))
        active_src = config.LIVE_DIR / "panels" / f"{panel.id}_active.png"
        active_file = None
        if active_src.exists():
            files_to_copy.append(
                (active_src, config.EXPORT_DIR / "panels" / f"{panel.id}_active.png")
            )
            active_file = f"panels/{panel.id}_active.png"
        manifest["feature_panels"].append({
            "id": panel.id,
            "file": f"panels/{panel.id}.png",
            "active_file": active_file,
            "bbox": list(panel.bbox),
            "target_size": list(panel.target_size),
            "active_kind": panel.active_kind,
        })

    # Board spaces — one file per design, manifest records every position.
    for design in catalog.all_space_designs():
        src = assets.live_path("spaces", design.id)
        if not src.exists():
            failures.append(f"space:{design.id}")
            continue
        dst = config.EXPORT_DIR / "spaces" / f"{design.id}.png"
        files_to_copy.append((src, dst))
        for ref in design.positions:
            x, y, w, h = catalog.board_spaces.resolve_position(ref)
            manifest["board_spaces"].append({
                "design_id": design.id,
                "space_kind": design.space_kind,
                "file": f"spaces/{design.id}.png",
                "position": [x, y],
                "size": [w, h],
                "layout_ref": ref,
            })

    # Preview.
    for name in ("board_idle.png", "board_active.png"):
        src = config.PREVIEW_DIR / name
        if src.exists():
            files_to_copy.append((src, config.EXPORT_DIR / "preview" / name))

    sink.start("copy live -> export", total=len(files_to_copy))
    for src, dst in files_to_copy:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        sink.step(dst.relative_to(config.EXPORT_DIR).as_posix())

    manifest_path = config.EXPORT_DIR / "board_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    sink.log(f"manifest -> {manifest_path}")
    sink.log(f"target   -> {config.EXPORT_DIR}")
    if failures:
        sink.log(f"exported with {len(failures)} missing tile(s): {', '.join(failures)}")

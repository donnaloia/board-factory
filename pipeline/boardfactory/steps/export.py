"""Step 8: Export approved assets + manifest to board_assets/.

Outputs three things for engine consumption:
1. Individual tile PNGs organized by category
2. A `board_manifest.json` mapping tile_id → file path + position + animation params
3. The composited board preview as a reference asset
"""

from __future__ import annotations

import json
import shutil

from .. import config
from ..progress import RunStats, progress_bar, step
from ..schemas import Catalog


def do_export(run: RunStats, catalog: Catalog) -> None:
    with step(run, "export") as s:
        manifest: dict = {
            "project": catalog.project,
            "board_size": list(catalog.board_size),
            "centerpiece": None,
            "feature_panels": [],
            "board_spaces": [],
        }

        files_to_copy: list[tuple] = []  # (src, dst, manifest_action)

        # Centerpiece
        cp_src = config.APPROVED_DIR / "centerpiece.png"
        if cp_src.exists():
            cp_dst = config.EXPORT_DIR / "centerpiece" / "centerpiece.png"
            files_to_copy.append((cp_src, cp_dst, None))
            cp_active = config.APPROVED_DIR / "centerpiece_active.png"
            if cp_active.exists():
                files_to_copy.append(
                    (cp_active, config.EXPORT_DIR / "centerpiece" / "centerpiece_active.png", None)
                )
            manifest["centerpiece"] = {
                "id": "centerpiece",
                "file": "centerpiece/centerpiece.png",
                "active_file": "centerpiece/centerpiece_active.png" if cp_active.exists() else None,
                "bbox": list(catalog.centerpiece.bbox),
                "target_size": list(catalog.centerpiece.target_size),
                "active_kind": catalog.centerpiece.active_kind,
            }

        # Feature panels
        for panel in catalog.all_panels():
            src = config.APPROVED_DIR / "panels" / f"{panel.id}.png"
            if not src.exists():
                s.failures.append(f"panel:{panel.id} not approved")
                continue
            dst = config.EXPORT_DIR / "panels" / f"{panel.id}.png"
            files_to_copy.append((src, dst, None))
            active_src = config.APPROVED_DIR / "panels" / f"{panel.id}_active.png"
            active_file = None
            if active_src.exists():
                files_to_copy.append((active_src, config.EXPORT_DIR / "panels" / f"{panel.id}_active.png", None))
                active_file = f"panels/{panel.id}_active.png"
            manifest["feature_panels"].append({
                "id": panel.id,
                "file": f"panels/{panel.id}.png",
                "active_file": active_file,
                "bbox": list(panel.bbox),
                "target_size": list(panel.target_size),
                "active_kind": panel.active_kind,
            })

        # Board spaces — record every position that uses each design
        for design in catalog.all_space_designs():
            src = config.APPROVED_DIR / "spaces" / f"{design.id}.png"
            if not src.exists():
                s.failures.append(f"space:{design.id} not approved")
                continue
            dst = config.EXPORT_DIR / "spaces" / f"{design.id}.png"
            files_to_copy.append((src, dst, None))
            for ref in design.positions:
                pos = catalog.board_spaces.resolve_position(ref)
                manifest["board_spaces"].append({
                    "design_id": design.id,
                    "file": f"spaces/{design.id}.png",
                    "position": list(pos),
                    "size": list(catalog.board_spaces.size),
                    "layout_ref": ref,
                })

        # Preview
        for name in ("board_idle.png", "board_active.png"):
            src = config.PREVIEW_DIR / name
            if src.exists():
                files_to_copy.append((src, config.EXPORT_DIR / "preview" / name, None))

        with progress_bar("Copying approved → board_assets", total=len(files_to_copy)) as bar:
            for src, dst, _ in files_to_copy:
                bar.set_current(str(dst.relative_to(config.EXPORT_DIR)))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                s.items += 1
                bar.advance()

        manifest_path = config.EXPORT_DIR / "board_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        s.extras["target"] = str(config.EXPORT_DIR.relative_to(config.REPO_ROOT))
        s.extras["manifest"] = "board_manifest.json"

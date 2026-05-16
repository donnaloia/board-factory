"""Pack and Publish operation.

Loads all generated clip frames from disk, packs them into a sprite-sheet
atlas, writes ``atlas.png`` and ``manifest.json`` to the live directory, and
archives the previous live pack (if any) to ``history/<run_id>/``.

This operation is deterministic — no AI calls, zero cost.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from PIL import Image

from ..schemas.manifest import AnimationManifest, DesignLock
from ..steps.atlas import pack_atlas
from .progress import ProgressSink


# Clips whose ``flip_x`` flag is True (runtime mirrors them for the opposite
# facing direction when ``facing_policy == "flip_x"``).
_FLIP_X_CLIP_SUFFIXES: tuple[str, ...] = ("_horizontal",)


def pack_publish(
    *,
    token_slug: str,
    board_id: str,
    design_lock: DesignLock,
    clips_root: Path,        # workspace/tokens/<slug>/clips/
    live_dir: Path,          # workspace/tokens/<slug>/animations/live/
    history_dir: Path,       # workspace/tokens/<slug>/animations/history/<run_id>/
    run_id: str,
    sink: ProgressSink,
) -> AnimationManifest:
    """Pack clips → atlas and publish to ``live_dir``.

    Returns the ``AnimationManifest`` that was written to
    ``live_dir/manifest.json``.
    """
    # ── 1. Archive existing live pack ─────────────────────────────────────────
    if live_dir.exists() and any(live_dir.iterdir()):
        sink.emit("progress", {"step": "archive_live"})
        history_dir.mkdir(parents=True, exist_ok=True)
        for f in live_dir.iterdir():
            shutil.copy2(f, history_dir / f.name)

    live_dir.mkdir(parents=True, exist_ok=True)

    # ── 2. Load frames from disk ───────────────────────────────────────────────
    clips_frames: dict[str, list[Image.Image]] = {}
    for clip_name in design_lock.clips:
        frames_dir = clips_root / clip_name / "frames"
        if not frames_dir.exists():
            sink.emit("warn", {"step": "missing_clip", "clip": clip_name})
            continue
        frame_paths = sorted(frames_dir.glob("frame_*.png"), key=_frame_sort_key)
        if not frame_paths:
            sink.emit("warn", {"step": "empty_clip", "clip": clip_name})
            continue
        clips_frames[clip_name] = [Image.open(str(p)).convert("RGBA") for p in frame_paths]
        sink.emit("progress", {"step": f"loaded_{clip_name}", "frames": len(frame_paths)})

    if not clips_frames:
        raise RuntimeError(
            f"No clip frames found for token {token_slug!r} under {clips_root}. "
            "Run generate_clip first."
        )

    # ── 3. Pack atlas ──────────────────────────────────────────────────────────
    sink.emit("progress", {"step": "pack_atlas"})
    flip_x = {
        name for name in clips_frames
        if any(name.endswith(sfx) for sfx in _FLIP_X_CLIP_SUFFIXES)
    }
    atlas, clip_entries = pack_atlas(
        clips_frames,
        canvas_w=design_lock.canvas_w,
        canvas_h=design_lock.canvas_h,
        frame_fps=design_lock.frame_fps,
        flip_x_clips=flip_x,
    )

    # ── 4. Write atlas ─────────────────────────────────────────────────────────
    atlas_path = live_dir / "atlas.png"
    atlas.save(str(atlas_path), format="PNG")
    sink.emit("progress", {"step": "atlas_written", "size": list(atlas.size)})

    # ── 5. Build + write manifest ──────────────────────────────────────────────
    edge_routing = _build_edge_routing(
        list(clips_frames.keys()), design_lock.locomotion_profile
    )
    manifest = AnimationManifest(
        token_slug=token_slug,
        run_id=run_id,
        canvas_w=design_lock.canvas_w,
        canvas_h=design_lock.canvas_h,
        pivot_x=design_lock.pivot_x,
        pivot_y=design_lock.pivot_y,
        clips=clip_entries,
        edge_kind_routing=edge_routing,
        created_ms=int(time.time() * 1000),
    )
    manifest_path = live_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    sink.emit("done", {"run_id": run_id, "clips": list(clip_entries.keys())})
    return manifest


# ── helpers ──────────────────────────────────────────────────────────────────

def _frame_sort_key(p: Path) -> int:
    """Sort ``frame_N.png`` by N numerically."""
    stem = p.stem  # "frame_3"
    try:
        return int(stem.split("_")[-1])
    except ValueError:
        return 0


def _build_edge_routing(clip_names: list[str], locomotion_profile: str) -> dict[str, str]:
    """Map edge directions to clip names based on what clips exist."""
    routing: dict[str, str] = {}

    horizontal = next(
        (n for n in clip_names if "horizontal" in n or "drift" in n or "fly" in n), None
    )
    idle = next((n for n in clip_names if "idle" in n), None)

    if horizontal:
        routing["horizontal"] = horizontal
    if horizontal and locomotion_profile == "walk":
        routing["vertical_up"] = horizontal
        routing["vertical_down"] = horizontal
    if idle:
        routing["idle"] = idle

    return routing

"""Sprite-sheet atlas packing.

Packs all frames for all clips into a single PNG atlas.  Layout is a
horizontal strip per clip: each row contains the frames of one clip laid
left to right.

The resulting atlas is sized to:
    width  = max_frames_per_clip × canvas_w
    height = n_clips × canvas_h

Returns the atlas image and a ``clips`` dict compatible with
``AnimationManifest.clips``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..schemas.manifest import ClipEntry, FrameRect


def pack_atlas(
    clips_frames: dict[str, list[Image.Image]],
    canvas_w: int,
    canvas_h: int,
    frame_fps: int = 12,
    flip_x_clips: set[str] | None = None,
) -> tuple[Image.Image, dict[str, ClipEntry]]:
    """Pack ``clips_frames`` into a single atlas image + manifest dict.

    ``clips_frames`` maps clip_name → ordered list of PIL frames (all must be
    exactly ``canvas_w × canvas_h`` RGBA images).

    ``flip_x_clips`` — set of clip names where the runtime may mirror the
    frames horizontally to produce the opposite facing direction.
    """
    if flip_x_clips is None:
        flip_x_clips = set()

    ordered_clips = list(clips_frames.items())
    if not ordered_clips:
        empty = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        return empty, {}

    max_frames = max(len(frames) for _, frames in ordered_clips)
    n_clips = len(ordered_clips)

    atlas_w = max_frames * canvas_w
    atlas_h = n_clips * canvas_h
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))

    clip_entries: dict[str, ClipEntry] = {}
    for row, (clip_name, frames) in enumerate(ordered_clips):
        rects: list[FrameRect] = []
        for col, frame in enumerate(frames):
            dst_x = col * canvas_w
            dst_y = row * canvas_h
            # Ensure exact canvas size
            if frame.size != (canvas_w, canvas_h):
                frame = frame.resize((canvas_w, canvas_h), Image.LANCZOS)
            atlas.paste(frame.convert("RGBA"), (dst_x, dst_y))
            rects.append(FrameRect(x=dst_x, y=dst_y, w=canvas_w, h=canvas_h))
        clip_entries[clip_name] = ClipEntry(
            frames=rects,
            fps=frame_fps,
            loop=True,
            flip_x=clip_name in flip_x_clips,
        )

    return atlas, clip_entries

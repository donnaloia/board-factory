"""Single-pass card assembly (default in production; tests force legacy with env)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from cardfactory.ops.generate_cards import generate_one_card
from cardfactory.providers.mock import MockCardProvider


class _ListSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int | None]] = []

    def emit(self, stage: str, msg: str, pct: int | None = None) -> None:
        self.events.append((stage, msg, pct))


def _synthetic_frame(canvas: tuple[int, int], inner: dict) -> Image.Image:
    w, h = canvas
    img = Image.new("RGBA", (w, h), (55, 45, 35, 255))
    ix, iy, iw, ih = inner["x"], inner["y"], inner["w"], inner["h"]
    hole = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    img.paste(hole, (ix, iy))
    return img


def test_generate_one_card_single_pass_writes_integrated_mask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARD_FACTORY_FINAL_UNIFY", "0")

    canvas = (64, 64)
    inner = {"x": 10, "y": 10, "w": 44, "h": 44}
    frame_path = tmp_path / "frame.png"
    _synthetic_frame(canvas, inner).save(frame_path)

    masks_dir = tmp_path / "masks"
    history_dir = tmp_path / "hist"
    out = tmp_path / "live.png"
    sink = _ListSink()

    generate_one_card(
        deck_id="deck-test",
        slot_index=0,
        frame_commit_id=1,
        committed_frame_png=frame_path,
        committed_inner_rect=inner,
        canvas=canvas,
        illustration_prompt="A pixel-art robot",
        stat_lines=["ATK 1"],
        palette_colors=[],
        provider=MockCardProvider(),
        output_path=out,
        masks_dir=masks_dir,
        history_dir=history_dir,
        sink=sink,
    )

    assert (masks_dir / "m_integrated.png").is_file()
    assert (masks_dir / "m_integrated_paint.png").is_file()
    assert out.is_file()
    assert (out.parent / "manifest.json").is_file()
    stages = [e[0] for e in sink.events]
    assert "integrated_inpaint" in stages
    assert "stats_band" not in stages

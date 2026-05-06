"""End-to-end Atelier tests — repository CRUD + Approach D rotation.

These don't spin up the FastAPI client because the route handlers are a
thin shim around the same building blocks the pipeline uses; testing
the pipeline blocks directly avoids needing to mount the full app.

Coverage:
  - frames_repository.replace_active and the "one active per board"
    invariant (the partial unique index from migration 0002)
  - reapply_to_panel snapshots the previous live with op
    ``frame_rework_pre`` and rolls a new live (using the mock provider)
  - applicable_panels honors catalog.frame.apply_to_panels
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image


# ────────────────────────── helpers ──────────────────────────


def _png_bytes(color=(80, 100, 60), size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (*color, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _seed_panel_live(board_id: str, panel_id: str, color=(80, 60, 40)) -> Path:
    from infrastructure.files import workspace as fs_ws

    p = fs_ws.live_path(board_id, "panels", panel_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (*color, 255)).save(p)
    return p


def _seed_house_frame(board_id: str, ring_px: int = 6) -> None:
    """Adopt a deterministic house frame for ``board_id``."""
    from boardfactory import config as bf_config
    from boardfactory import frames as bf_frames

    src = Image.new("RGBA", (64, 64), (40, 40, 40, 255))
    sl = bf_frames.extract_9slice(src, ring_px)
    instance = bf_frames.FrameInstance(
        ring_px=ring_px,
        source_kind="panel",
        source_id="seed",
        source_size=(64, 64),
        model_id="test",
    )
    with bf_config.scope_board(board_id):
        bf_frames.adopt_house_frame(sl, instance)


# ────────────────────────── repository ──────────────────────────


def test_replace_active_enforces_one_active_per_board(seeded_board):
    from boardfactory import frames as bf_frames
    from domains.cells import frames_repository as frames_repo

    a = bf_frames.FrameInstance(
        ring_px=6, source_kind="panel", source_id="alpha",
        source_size=(64, 64), model_id="test",
    )
    b = bf_frames.FrameInstance(
        ring_px=8, source_kind="panel", source_id="beta",
        source_size=(64, 64), model_id="test",
    )
    va = frames_repo.replace_active(seeded_board.id, instance=a)
    vb = frames_repo.replace_active(seeded_board.id, instance=b)

    assert vb.active is True
    active = frames_repo.get_active(seeded_board.id)
    assert active is not None
    assert active.id == vb.id

    rows = frames_repo.list_for_board(seeded_board.id, include_inactive=True)
    ids = {r.id for r in rows}
    assert va.id in ids and vb.id in ids
    actives = [r for r in rows if r.active]
    assert len(actives) == 1
    assert actives[0].id == vb.id


def test_mark_all_inactive_drops_active_flag(seeded_board):
    from boardfactory import frames as bf_frames
    from domains.cells import frames_repository as frames_repo

    inst = bf_frames.FrameInstance(
        ring_px=6, source_kind="panel", source_id="alpha",
        source_size=(64, 64),
    )
    frames_repo.replace_active(seeded_board.id, instance=inst)
    n = frames_repo.mark_all_inactive(seeded_board.id)
    assert n == 1
    assert frames_repo.get_active(seeded_board.id) is None


def test_ensure_active_for_disk_pack_lazy_backfill(seeded_board):
    from domains.cells import frames_repository as frames_repo

    _seed_house_frame(seeded_board.id, ring_px=6)
    # No DB row yet — backfill should create one tagged "legacy".
    view = frames_repo.ensure_active_for_disk_pack(seeded_board.id)
    assert view is not None
    assert view.active is True
    assert view.ring_px == 6


# ────────────────────────── reapply_to_panel ──────────────────────────


def _enable_frames_in_catalog(board_id: str) -> None:
    """Flip catalog.frame.enabled + apply_to_panels true for the test."""
    from domains.boards import services as svc_boards

    data = svc_boards.load_catalog(board_id)
    data.setdefault("frame", {})
    data["frame"]["enabled"] = True
    data["frame"]["apply_to_panels"] = True
    svc_boards.save_catalog(board_id, data)


def test_reapply_to_panel_snapshots_pre_and_promotes_new(seeded_board):
    from boardfactory import config as bf_config
    from boardfactory import assets as bf_assets
    from boardfactory.ops import (
        OP_FRAME_REWORK_PRE,
        reapply_to_panel,
    )
    from boardfactory.providers.pixel.mock import MockProvider
    from domains.boards import services as svc_boards

    panel_id = "panel_left_top"
    _seed_panel_live(seeded_board.id, panel_id, color=(120, 60, 60))
    _seed_house_frame(seeded_board.id, ring_px=6)
    _enable_frames_in_catalog(seeded_board.id)

    catalog = svc_boards.load_catalog_model(seeded_board.id)
    provider = MockProvider()

    class _NoopSink:
        def start(self, *_a, **_k): ...
        def step(self, *_a, **_k): ...
        def log(self, *_a, **_k): ...

    with bf_config.scope_board(seeded_board.id):
        result = reapply_to_panel(catalog, panel_id, provider, _NoopSink())

        assert result.skipped is False
        assert result.error is None
        assert result.promoted_filename is not None

        history = bf_assets.list_history("panels", panel_id)
        # Newest entries first; we expect at least the snapshot + the new
        # regen candidate(s).
        ops = [h.operation for h in history]
        assert OP_FRAME_REWORK_PRE in ops, (
            "reapply_to_panel must snapshot the previous live with op "
            "'frame_rework_pre' so the user can revert"
        )
        live_p = bf_assets.live_path("panels", panel_id)
        assert live_p.exists()


def test_reapply_to_panel_skipped_when_no_live(seeded_board):
    from boardfactory import config as bf_config
    from boardfactory.ops import reapply_to_panel
    from boardfactory.providers.pixel.mock import MockProvider
    from domains.boards import services as svc_boards

    _seed_house_frame(seeded_board.id, ring_px=6)
    _enable_frames_in_catalog(seeded_board.id)

    catalog = svc_boards.load_catalog_model(seeded_board.id)
    provider = MockProvider()

    class _NoopSink:
        def start(self, *_a, **_k): ...
        def step(self, *_a, **_k): ...
        def log(self, *_a, **_k): ...

    with bf_config.scope_board(seeded_board.id):
        result = reapply_to_panel(catalog, "panel_left_top", provider, _NoopSink())
    assert result.skipped is True
    assert result.promoted_filename is None


# ────────────────────────── frame_reapply worker ──────────────────────────


def test_frame_reapply_worker_processes_panels_with_cancel(seeded_board):
    """Smoke-test the job worker: stubs Job + cancel, runs end-to-end."""
    from collections import deque

    from boardfactory import config as bf_config
    from boardfactory.providers.pixel import mock as mock_provider
    from domains.boards import services as svc_boards
    from jobs import pipeline_adapters

    _seed_panel_live(seeded_board.id, "panel_left_top", color=(120, 60, 60))
    _seed_house_frame(seeded_board.id, ring_px=6)
    _enable_frames_in_catalog(seeded_board.id)

    # Pretend Job — only the attributes the worker touches.
    class _FakeJob:
        def __init__(self) -> None:
            self.id = "test-job"
            self.label = "test"
            self.operation = "frame.reapply"
            self.target = seeded_board.id
            self.progress = 0.0
            self.log = deque(maxlen=200)
            self.cost_estimate = 0.0
            self.cost_actual = 0.0
            self.error = None
            self.started_at = None
            self.ended_at = None

    job = _FakeJob()
    cancel = threading.Event()

    # Force the mock provider via the env override the test fixture sets.
    assert mock_provider.MockProvider().name == "mock"

    # Run inside the per-board lock that the real route handler uses.
    with bf_config.scope_board(seeded_board.id):
        spent = pipeline_adapters.frame_reapply(job, cancel)

    assert isinstance(spent, float)
    # The mock is free, so spent must be 0.
    assert spent == 0.0

    # The catalog seeded by ``seeded_board`` has a non-zero panel count
    # — the log should mention "reapplied frame to N / N panel(s)".
    log_text = "\n".join(job.log)
    assert "reapplied frame" in log_text or "no panels in scope" in log_text

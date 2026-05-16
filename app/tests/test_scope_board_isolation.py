"""Regression tests for the per-board lock isolation between writes and reads.

Background
----------
The web app uses a per-board re-entrant lock to serialize *mutating* pipeline
work for the same board (so two writers can't trample each other on
``data/boards/<id>/workspace/``).  Read-only paths like the side panel's
``/api/cell`` fetch only need the *thread-local active board* set so path
helpers (``config.LIVE_DIR`` etc.) resolve to the right board — they do not
need to acquire the lock.

The original bug was that both code paths went through ``scope_board()``,
which acquires the lock.  When a long pipeline job (e.g. ``regen.spaces``)
held the lock for ~30 seconds while talking to a provider, every subsequent
``/api/cell`` request for the same board blocked behind the lock and the
side panel appeared to freeze when the user clicked another space.

Fix: split ``scope_board()`` into two context managers:

* ``scope_board(board_id)`` — write side. Takes the per-board lock + sets
  the thread-local active board. Used by pipeline jobs and by handlers that
  actually mutate workspace/ (``promote``, frame adoption, etc.).
* ``set_active_board(board_id)`` — read side. Sets the thread-local active
  board only; never blocks. Used by ``/api/cell`` and other read paths.

These tests pin both halves of that contract.
"""

from __future__ import annotations

import threading
import time

import pytest


# ─── Unit-level: lock isolation between scope_board and set_active_board ───


def test_set_active_board_does_not_block_when_writer_holds_lock():
    """The reader must not wait for an in-flight writer on the same board.

    This is the core invariant the production bug violated.
    """
    from boardfactory import config as bf_config

    board = "iso-board"
    writer_acquired = threading.Event()
    writer_release = threading.Event()
    reader_started = threading.Event()
    reader_finished = threading.Event()

    def writer() -> None:
        with bf_config.scope_board(board):
            writer_acquired.set()
            # Hold the lock for "a while" — simulates a pipeline job
            # talking to a provider. Without the fix, the reader below
            # would be blocked on this for the full timeout.
            writer_release.wait(timeout=5.0)

    def reader() -> None:
        # Wait until the writer is definitely inside the locked block.
        assert writer_acquired.wait(timeout=2.0)
        reader_started.set()
        with bf_config.set_active_board(board):
            assert bf_config.active_board() == board
        reader_finished.set()

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()

    # The reader must finish even though the writer is still holding the
    # lock. Give it a generous bound to account for thread scheduling but
    # still much less than the writer's hold time.
    assert reader_finished.wait(timeout=1.0), (
        "set_active_board() blocked on the per-board write lock — the "
        "side-panel-freeze regression has reappeared."
    )

    # Tear down the writer.
    writer_release.set()
    wt.join(timeout=2.0)
    rt.join(timeout=2.0)
    assert not wt.is_alive()
    assert not rt.is_alive()


def test_scope_board_still_serializes_two_writers_on_same_board():
    """``scope_board()`` is the write lock — concurrent writers must serialize."""
    from boardfactory import config as bf_config

    board = "ser-board"
    second_writer_acquired = threading.Event()
    inside_first = threading.Event()
    release_first = threading.Event()

    def first_writer() -> None:
        with bf_config.scope_board(board):
            inside_first.set()
            release_first.wait(timeout=5.0)

    def second_writer() -> None:
        with bf_config.scope_board(board):
            second_writer_acquired.set()

    t1 = threading.Thread(target=first_writer)
    t2 = threading.Thread(target=second_writer)
    t1.start()
    assert inside_first.wait(timeout=2.0)
    t2.start()

    # The second writer must be blocked while the first holds the lock.
    assert not second_writer_acquired.wait(timeout=0.2)

    # Release the first; the second must then acquire promptly.
    release_first.set()
    assert second_writer_acquired.wait(timeout=2.0)

    t1.join(timeout=2.0)
    t2.join(timeout=2.0)


def test_scope_board_does_not_block_writers_on_different_boards():
    """Per-board locking — unrelated boards proceed concurrently."""
    from boardfactory import config as bf_config

    a_inside = threading.Event()
    release_a = threading.Event()
    b_acquired = threading.Event()

    def writer_a() -> None:
        with bf_config.scope_board("board-a"):
            a_inside.set()
            release_a.wait(timeout=5.0)

    def writer_b() -> None:
        with bf_config.scope_board("board-b"):
            b_acquired.set()

    ta = threading.Thread(target=writer_a)
    tb = threading.Thread(target=writer_b)
    ta.start()
    assert a_inside.wait(timeout=2.0)
    tb.start()
    assert b_acquired.wait(timeout=1.0), (
        "scope_board('board-b') blocked on a lock held for 'board-a' — "
        "per-board lock isolation is broken."
    )

    release_a.set()
    ta.join(timeout=2.0)
    tb.join(timeout=2.0)


def test_set_active_board_restores_previous_thread_local():
    """Nesting must not leak — exiting set_active_board restores the prior board."""
    from boardfactory import config as bf_config

    bf_config.set_board(None)
    assert bf_config.active_board() is None

    with bf_config.set_active_board("outer"):
        assert bf_config.active_board() == "outer"
        with bf_config.set_active_board("inner"):
            assert bf_config.active_board() == "inner"
        assert bf_config.active_board() == "outer"

    assert bf_config.active_board() is None


# ─── Integration: side-panel hydration during an in-flight pipeline write ───


def test_build_cell_side_panel_payload_does_not_block_on_running_writer(
    seeded_board, board_id
):
    """End-to-end: ``/api/cell``-shaped read must return promptly even if a
    writer (e.g. ``regen.spaces``) is holding the per-board lock.

    This is the exact scenario the user hit: click 'Generate' on space A,
    job runs, click space B, side panel hangs. After the fix the side panel
    request returns in milliseconds.
    """
    from boardfactory import config as bf_config

    from domains.spaces import services as spaces_services
    from infrastructure import deps as route_deps

    # Pick a real space id from the seeded catalog so we exercise the full
    # build_cell_side_panel_payload path (history listing + frame meta).
    catalog = route_deps.load_board_catalog(board_id)
    designs = catalog["board_spaces"]["designs"]
    target_id = next(d["id"] for d in designs if d.get("positions"))

    writer_acquired = threading.Event()
    writer_release = threading.Event()

    def hold_write_lock() -> None:
        # Mimic what scoped_pipeline_callable does inside the worker thread:
        # take scope_board(...) and stay inside it.
        with bf_config.scope_board(board_id):
            writer_acquired.set()
            writer_release.wait(timeout=5.0)

    writer = threading.Thread(target=hold_write_lock, daemon=True)
    writer.start()
    try:
        assert writer_acquired.wait(timeout=2.0)

        t0 = time.perf_counter()
        payload = spaces_services.build_cell_side_panel_payload(
            board_id, "spaces", target_id,
        )
        elapsed = time.perf_counter() - t0

        # Primary signal: a writer is still inside its locked block while
        # we run the read. If this fails, the elapsed assertion below tells
        # us *how long* we ended up waiting on the lock.
        still_holding_write = writer.is_alive()

        # Loose upper bound — the read itself is dominated by Postgres +
        # listdir on a fresh board (typically <30ms locally, a bit higher
        # over a real network). Anything north of 500ms means we re-acquired
        # the write lock somewhere on the read path. Assert this BEFORE
        # still_holding_write because it's the more diagnostic failure
        # (tells you how long you blocked).
        assert elapsed < 0.5, (
            f"build_cell_side_panel_payload took {elapsed:.3f}s while a "
            f"writer held scope_board({board_id!r}); the side-panel "
            f"freeze regression has reappeared."
        )
        assert still_holding_write, (
            "Writer thread terminated before the read finished — most "
            "likely the read blocked on the write lock long enough for "
            "the writer's release-timeout to fire."
        )
        # Sanity: we got a real payload, not an exception or empty dict.
        assert payload["spec"]["id"] == target_id
        assert payload["category"] == "spaces"
    finally:
        writer_release.set()
        writer.join(timeout=2.0)

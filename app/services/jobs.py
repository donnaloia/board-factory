"""Job enqueue helpers.

Thin wrapper around ``jobs.JobRunner`` and ``boardfactory.config.scope_board``.
Route handlers should call these helpers rather than importing ``jobs`` directly
so use-case glue stays in one place.

The split between ``services.jobs`` (app-facing API) and ``jobs.py`` (in-process
runner, DB snapshots, asyncio) is deliberate: ``jobs.py`` stays free of
FastAPI and template code.
"""

from __future__ import annotations

from typing import Callable

from jobs import get_runner


def enqueue(
    *,
    label: str,
    operation: str,
    target: str | None,
    cost_estimate: float,
    fn: Callable,
) -> str:
    """Register ``fn`` to run on the runner's worker pool. Returns the job id."""
    runner = get_runner()
    job = runner.enqueue(
        label=label,
        operation=operation,
        target=target,
        cost_estimate=cost_estimate,
        fn=fn,
    )
    return job.id


def scoped(board_id: str, fn: Callable) -> Callable:
    """Wrap ``fn`` so it executes inside ``config.scope_board(board_id)``.

    Lazy import of ``boardfactory.config`` keeps the test harness from
    needing the pipeline package on its hot path when only the runner
    is exercised.
    """
    from boardfactory import config as bf_config

    def wrapped(job, cancel):
        with bf_config.scope_board(board_id):
            try:
                from services import workspace_palette as _wp

                _wp.materialize_palette_to_disk(board_id)
            except Exception:
                pass
            return fn(job, cancel)

    return wrapped

"""In-process async job runner for pipeline operations.

The web app needs to invoke pipeline ops without blocking the HTTP request,
surface live progress to the browser, allow cancel, and track cost. This
module is the small piece that does that.

Design choices:
- In-memory only. Single-user local app; restart loses queued jobs and any
  job-specific log buffers. Live + history assets persist on disk.
- One asyncio task per running job, dispatched via run_in_executor since the
  underlying pipeline functions are blocking (PIL, httpx sync client, etc.).
- Per-job progress is reported through a structured `JobProgressSink` that
  maps `start/step/log` events onto job.progress + job.log. The pipeline
  doesn't know about FastAPI — it only sees the `ProgressSink` protocol.
- Simple in-memory pub/sub for SSE: each subscriber gets an asyncio.Queue
  fed every status change. Subscribers can drop without affecting others.

This module stays UI-framework-agnostic: no FastAPI imports, no templating.
The web layer is the caller.
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


# ────────────────────────── data model ──────────────────────────


JobStatus = str  # "queued" | "running" | "done" | "failed" | "killed"


@dataclass
class Job:
    id: str
    label: str                      # human-friendly, "Generate · brazier_demon"
    operation: str                  # machine, "generate.panel"
    target: str | None              # asset id or category, "brazier_demon"
    status: JobStatus = "queued"
    progress: float = 0.0           # 0..1, or 0 if unknown
    eta_s: float | None = None      # seconds remaining, if estimable
    cost_estimate: float = 0.0      # USD, set on enqueue
    cost_actual: float = 0.0        # USD, set on completion (provider-reported)
    started_at: float | None = None
    ended_at: float | None = None
    error: str | None = None
    log: deque[str] = field(default_factory=lambda: deque(maxlen=500))

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at if self.ended_at else time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "operation": self.operation,
            "target": self.target,
            "status": self.status,
            "progress": round(self.progress, 3),
            "eta_s": round(self.eta_s, 1) if self.eta_s is not None else None,
            "cost_estimate": round(self.cost_estimate, 4),
            "cost_actual": round(self.cost_actual, 4),
            "elapsed_s": round(self.elapsed(), 1),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "log_tail": list(self.log)[-12:],
        }


# ────────────────────────── runner ──────────────────────────


class JobRunner:
    """Owns the registry of active and completed jobs plus the pub/sub channel.

    There is exactly one JobRunner per process. The web app constructs it at
    startup and reuses it for every request.
    """

    def __init__(self, max_history: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._history: deque[str] = deque(maxlen=max_history)  # completed-job IDs in order
        self._lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue] = []

    # ─── enqueue ───

    def enqueue(
        self,
        *,
        label: str,
        operation: str,
        target: str | None,
        cost_estimate: float,
        fn: Callable[[Job, threading.Event], float | None],
    ) -> Job:
        """Register a new job and start it. fn runs in a worker thread.

        fn signature: (job, cancel_event) -> actual_cost_usd | None
        - It receives the Job so it can append to job.log and update progress.
        - cancel_event is set when the user clicks the kill button. fn should
          check it periodically and raise JobCancelled if set.
        - Return value (a float) sets job.cost_actual. Returning None leaves
          it at the cost_estimate.
        """
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            label=label,
            operation=operation,
            target=target,
            cost_estimate=cost_estimate,
        )
        cancel = threading.Event()
        self._jobs[job_id] = job
        self._cancel_events[job_id] = cancel

        loop = asyncio.get_running_loop()
        task = loop.create_task(self._run(job, cancel, fn))
        self._tasks[job_id] = task
        self._publish(job)
        return job

    # ─── execution ───

    async def _run(
        self,
        job: Job,
        cancel: threading.Event,
        fn: Callable[[Job, threading.Event], float | None],
    ) -> None:
        """Drive one job through its lifecycle. Runs the worker function in
        an executor thread, then publishes terminal state regardless of outcome."""
        job.status = "running"
        job.started_at = time.time()
        self._publish(job)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, fn, job, cancel)
            if cancel.is_set():
                job.status = "killed"
            else:
                job.status = "done"
                if isinstance(result, (int, float)):
                    job.cost_actual = float(result)
                else:
                    job.cost_actual = job.cost_estimate
                job.progress = 1.0
        except JobCancelled:
            job.status = "killed"
        except Exception as e:
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.log.append(f"FAIL: {job.error}")
            for line in traceback.format_exc().splitlines()[-6:]:
                job.log.append(line)
        finally:
            job.ended_at = time.time()
            self._history.append(job.id)
            self._tasks.pop(job.id, None)
            self._cancel_events.pop(job.id, None)
            self._publish(job)

    # ─── kill ───

    def kill(self, job_id: str) -> bool:
        ev = self._cancel_events.get(job_id)
        if ev is None:
            return False
        ev.set()
        job = self._jobs.get(job_id)
        if job:
            job.log.append("← cancel requested by user")
            self._publish(job)
        return True

    # ─── inspection ───

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all_jobs(self) -> list[Job]:
        """All jobs we still know about, newest-first."""
        return sorted(self._jobs.values(), key=lambda j: j.started_at or 0, reverse=True)

    def active_jobs(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status in ("queued", "running")]

    # ─── pub/sub ───

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _publish(self, job: Job) -> None:
        payload = job.to_dict()
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


class JobCancelled(Exception):
    """Raised inside a worker when the cancel event is set."""


# ────────────────────────── job-side helpers ──────────────────────────


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise JobCancelled()


class JobProgressSink:
    """Adapter that maps `ProgressSink` events onto a `Job`.

    The pipeline ops call `start/step/log` on whatever sink they're given;
    here we translate those into:

      - `job.progress` (0.0 -> 1.0) so the front-end can draw a real bar
      - `job.log`      (a deque of strings) so the job tray shows live notes
      - re-publish on every event so SSE subscribers see updates immediately

    `start` resets the progress numerator/denominator. Nested orchestrators
    (a "generate all panels" loop calling `draw_cell` per panel) wrap their
    inner calls in `_InnerSink` from boardfactory.ops.orchestrate so the
    inner `start()` doesn't reset the outer bar.
    """

    def __init__(self, job: Job, runner: "JobRunner | None" = None):
        self._job = job
        self._runner = runner
        self._total = 0
        self._done = 0

    def start(self, label: str, total: int) -> None:
        self._total = max(int(total), 0)
        self._done = 0
        self._job.progress = 0.0 if self._total else 1.0
        self._job.log.append(f"{label}  (0/{self._total})")
        self._publish()

    def step(self, label: str, advance: int = 1) -> None:
        self._done += int(advance)
        if self._total:
            self._job.progress = min(1.0, self._done / self._total)
        else:
            # Unknown-total mode — still log so the user sees motion.
            self._job.progress = min(1.0, self._job.progress + 0.05)
        self._job.log.append(f"  {label}  ({self._done}/{self._total or '?'})")
        self._publish()

    def log(self, msg: str) -> None:
        self._job.log.append(str(msg))
        self._publish()

    def _publish(self) -> None:
        if self._runner is not None:
            self._runner._publish(self._job)


# ────────────────────────── singleton ──────────────────────────


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner

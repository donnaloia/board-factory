"""Pure DB I/O for ``job_runs`` (terminal job snapshots).

Hot jobs live in memory inside :mod:`jobs.runner`. When a job reaches a
terminal state (``done`` / ``failed`` / ``killed``) its snapshot is
persisted here so the job-tray survives process restarts. Hydration on
boot reads the newest N rows and replays them back into the runner.

This module is intentionally narrow — three functions:

* :func:`persist_terminal` — write/update one ``job_runs`` row.
* :func:`load_recent_jobs` — pull the newest N back as in-memory ``Job``
  objects.
* :func:`delete_job_run` — remove one row when the user dismisses from the tray.

Anything else (cost aggregation, cost recording) lives in
:mod:`jobs.cost_ledger`.
"""

from __future__ import annotations

import json
from collections import deque
from typing import TYPE_CHECKING

from sqlalchemy import select

from infrastructure.db import session_scope
from jobs.models import JobRunRecord

if TYPE_CHECKING:
    from jobs.runner import Job


def delete_job_run(job_id: str) -> bool:
    """Remove one persisted job snapshot (user dismissed from tray)."""
    with session_scope() as session:
        row = session.get(JobRunRecord, job_id)
        if row is None:
            return False
        session.delete(row)
        return True


def persist_terminal(job: Job) -> None:
    """Write completed / failed / killed jobs to the database."""
    log_list = list(job.log)[-500:]
    payload = {
        "id": job.id,
        "label": job.label,
        "operation": job.operation,
        "target": job.target,
        "status": job.status,
        "progress": job.progress,
        "eta_s": job.eta_s,
        "cost_estimate": job.cost_estimate,
        "cost_actual": job.cost_actual,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "error": job.error,
        "log_json": log_list,
    }
    with session_scope() as session:
        row = session.get(JobRunRecord, job.id)
        if row is None:
            row = JobRunRecord(id=job.id)
            session.add(row)
        row.label = payload["label"]
        row.operation = payload["operation"]
        row.target = payload["target"]
        row.status = payload["status"]
        row.progress = float(payload["progress"])
        row.eta_s = payload["eta_s"]
        row.cost_estimate = float(payload["cost_estimate"])
        row.cost_actual = float(payload["cost_actual"])
        row.started_at = payload["started_at"]
        row.ended_at = payload["ended_at"]
        row.error = payload["error"]
        row.log_json = json.dumps(payload["log_json"])


def load_recent_jobs(limit: int) -> list[Job]:
    """Hydrate the newest ``limit`` terminal jobs (ended_at descending)."""
    from jobs.runner import Job  # noqa: PLC0415

    jobs: list[Job] = []
    with session_scope() as session:
        rows = session.scalars(
            select(JobRunRecord).order_by(JobRunRecord.ended_at.desc().nulls_last()).limit(limit)
        ).all()
    for row in rows:
        try:
            log_tail = json.loads(row.log_json or "[]")
            if not isinstance(log_tail, list):
                log_tail = []
        except json.JSONDecodeError:
            log_tail = []
        dq: deque[str] = deque(log_tail, maxlen=500)
        jobs.append(
            Job(
                id=row.id,
                label=row.label,
                operation=row.operation,
                target=row.target,
                status=row.status,
                progress=float(row.progress),
                eta_s=row.eta_s,
                cost_estimate=float(row.cost_estimate),
                cost_actual=float(row.cost_actual),
                started_at=row.started_at,
                ended_at=row.ended_at,
                error=row.error,
                log=dq,
            )
        )
    return jobs

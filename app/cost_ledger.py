"""Cost ledger backed by ``cost_entries`` in SQL.

``record()`` is safe from worker threads — each call opens a short-lived session.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from sqlalchemy import select

from storage.db import session_scope
from models.core import CostEntryRecord


_lock = Lock()
_session_started = time.time()


def record(operation: str, target: str | None, units: int, usd: float) -> None:
    if usd <= 0:
        return
    entry_ts = time.time()
    with _lock:
        with session_scope() as session:
            session.add(
                CostEntryRecord(
                    ts=entry_ts,
                    op=operation,
                    target=target,
                    units=int(units),
                    usd=round(float(usd), 4),
                )
            )


def summary() -> dict:
    with session_scope() as session:
        all_rows = session.scalars(select(CostEntryRecord)).all()
    lifetime_usd = sum(float(r.usd) for r in all_rows)
    session_rows = [r for r in all_rows if float(r.ts) >= _session_started]
    session_usd = sum(float(r.usd) for r in session_rows)

    by_op_session: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "count": 0})
    for r in session_rows:
        b = by_op_session[r.op]
        b["usd"] += float(r.usd)
        b["count"] += 1

    return {
        "session_usd": round(session_usd, 4),
        "lifetime_usd": round(lifetime_usd, 4),
        "session_count": len(session_rows),
        "lifetime_count": len(all_rows),
        "by_operation": [
            {"op": op, "usd": round(b["usd"], 4), "count": b["count"]}
            for op, b in sorted(by_op_session.items(), key=lambda kv: -kv[1]["usd"])
        ],
    }


def session_started() -> float:
    return _session_started

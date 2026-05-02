"""Cost ledger in SQLite; legacy ``workspace/.costs.jsonl`` imported once.

``record()`` is safe from worker threads — each call opens a short-lived session.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock

from sqlalchemy import func, select

from storage.db import session_scope
from storage.models.core import CostEntryRecord


def repo_root() -> Path:
    return Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def ledger_jsonl_path() -> Path:
    return repo_root() / "workspace" / ".costs.jsonl"


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


def import_from_jsonl_if_needed() -> None:
    path = ledger_jsonl_path()
    if not path.exists():
        return
    with session_scope() as session:
        n = session.scalar(select(func.count()).select_from(CostEntryRecord)) or 0
        if int(n) > 0:
            return
        rows: list[CostEntryRecord] = []
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(
                    CostEntryRecord(
                        ts=float(e.get("ts") or 0),
                        op=str(e.get("op") or "unknown"),
                        target=e.get("target"),
                        units=int(e.get("units") or 1),
                        usd=float(e.get("usd") or 0),
                    )
                )
        except Exception:
            return
        session.add_all(rows)


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

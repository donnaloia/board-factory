"""Append-only cost ledger persisted at workspace/.costs.jsonl.

One line per provider-billed operation: timestamp, op, target, units, usd.

The web app surfaces two numbers in the header:
- session: sum of entries written since this process started
- lifetime: sum of all entries ever written

Plus a hover breakdown by operation. The ledger is intentionally simple JSONL
so it's easy to grep, edit, and back up.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock


REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
LEDGER_PATH = REPO_ROOT / "workspace" / ".costs.jsonl"


_lock = Lock()
_session_started = time.time()


def record(operation: str, target: str | None, units: int, usd: float) -> None:
    """Append a cost entry. Safe to call from worker threads."""
    if usd <= 0:
        return
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "op": operation,
        "target": target,
        "units": units,
        "usd": round(usd, 4),
    }
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    with _lock:
        with LEDGER_PATH.open("a") as f:
            f.write(line)


def _read_all() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    out: list[dict] = []
    with LEDGER_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summary() -> dict:
    """Return the breakdown the header cost meter renders.

    {
      "session_usd": float,
      "lifetime_usd": float,
      "session_count": int,
      "lifetime_count": int,
      "by_operation": [{"op": str, "usd": float, "count": int}, ...]   # session
    }
    """
    entries = _read_all()
    lifetime_usd = sum(e.get("usd", 0.0) for e in entries)
    session = [e for e in entries if e.get("ts", 0) >= _session_started]
    session_usd = sum(e.get("usd", 0.0) for e in session)

    by_op_session: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "count": 0})
    for e in session:
        b = by_op_session[e["op"]]
        b["usd"] += e.get("usd", 0.0)
        b["count"] += 1

    return {
        "session_usd": round(session_usd, 4),
        "lifetime_usd": round(lifetime_usd, 4),
        "session_count": len(session),
        "lifetime_count": len(entries),
        "by_operation": [
            {"op": op, "usd": round(b["usd"], 4), "count": b["count"]}
            for op, b in sorted(by_op_session.items(), key=lambda kv: -kv[1]["usd"])
        ],
    }


def session_started() -> float:
    return _session_started

"""Browser sessions persisted in SQLite (cookie still holds signed sid).

Cookie format unchanged (itsdangerous). Restarting Uvicorn no longer logs users
out as long as the DB file survives.
"""

from __future__ import annotations

import os
import secrets
import time

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete

from storage.db import session_scope
from models.core import BrowserSessionRecord


COOKIE_NAME = "bf_session"
SESSION_TTL_SEC = 30 * 24 * 3600  # 30 days idle

_SECRET = os.environ.get("BOARDFACTORY_SECRET") or "dev-only-secret-change-me"
_signer = URLSafeSerializer(_SECRET, salt="bf-session")


def create(user_id: str) -> str:
    sid = secrets.token_urlsafe(24)
    now = int(time.time() * 1000)
    with session_scope() as session:
        session.add(
            BrowserSessionRecord(
                sid=sid,
                user_id=user_id,
                created_ms=now,
                last_seen_ms=now,
            )
        )
    return _signer.dumps(sid)


def resolve(cookie_value: str | None) -> str | None:
    if not cookie_value:
        return None
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return None
    if not isinstance(sid, str):
        return None
    now = int(time.time() * 1000)
    with session_scope() as session:
        row = session.get(BrowserSessionRecord, sid)
        if row is None:
            return None
        if (now - row.last_seen_ms) > SESSION_TTL_SEC * 1000:
            session.delete(row)
            return None
        row.last_seen_ms = now
        return row.user_id


def destroy(cookie_value: str | None) -> None:
    if not cookie_value:
        return
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return
    if not isinstance(sid, str):
        return
    with session_scope() as session:
        row = session.get(BrowserSessionRecord, sid)
        if row is not None:
            session.delete(row)


def destroy_all_for_user(user_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(BrowserSessionRecord).where(BrowserSessionRecord.user_id == user_id))

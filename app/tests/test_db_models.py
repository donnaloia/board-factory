"""ORM persistence smoke tests across the auth + jobs domains.

Covers: ``users``, ``sessions``, ``cost_ledger`` (jobs domain), and
``job_runs`` snapshot persistence. These are the small "does the schema
match the model?" tests, not the big integration tests.
"""

from __future__ import annotations

import pytest


def test_user_create_find_keys(isolated_repo):
    from auth import services as auth_services

    assert auth_services.is_setup_required() is True
    u = auth_services.create_first_user(
        email="a@example.com", password="password99", display_name="Ada"
    )
    assert auth_services.is_setup_required() is False
    assert auth_services.find_by_email("a@example.com").id == u.id
    auth_services.update_api_keys(u.id, pixellab_api_key="pk-test", openai_api_key="sk-test")
    again = auth_services.find_by_id(u.id)
    assert again.pixellab_api_key == "pk-test"
    assert again.openai_api_key == "sk-test"
    pub = again.public_dict()
    assert pub["pixellab_api_key_set"] is True
    assert pub["openai_api_key_set"] is True


def test_session_cookie_roundtrip(isolated_repo):
    from auth import services as auth_services

    u = auth_services.create_first_user(email="s@example.com", password="password99")
    cookie = auth_services.create_session_cookie(u.id)
    assert auth_services.resolve_session_cookie(cookie) == u.id
    assert auth_services.resolve_session_cookie(cookie) == u.id  # sliding refresh
    auth_services.destroy_session_cookie(cookie)
    assert auth_services.resolve_session_cookie(cookie) is None


def test_register_user_second_account(isolated_repo):
    from auth import services as auth_services

    auth_services.create_first_user(email="first@example.com", password="password99")
    u2 = auth_services.register_user(
        email="second@example.com", password="password99", display_name="Two"
    )
    assert auth_services.find_by_email("second@example.com").id == u2.id
    assert u2.username


def test_register_user_rejects_duplicate_email(isolated_repo):
    from auth import services as auth_services

    auth_services.create_first_user(email="same@example.com", password="password99")
    with pytest.raises(ValueError, match="already exists"):
        auth_services.register_user(email="same@example.com", password="password99")


def test_create_first_user_still_single_setup(isolated_repo):
    from auth import services as auth_services

    auth_services.create_first_user(email="only@example.com", password="password99")
    with pytest.raises(ValueError, match="closed"):
        auth_services.create_first_user(email="other@example.com", password="password99")


def test_cost_ledger_summary(isolated_repo):
    from jobs import cost_ledger

    cost_ledger.record("gen.test", "space_a", 2, 0.05)
    s = cost_ledger.summary()
    assert s["lifetime_count"] >= 1
    assert s["lifetime_usd"] >= 0.05


def test_job_run_persist_reload(isolated_repo):
    from jobs.runner import Job
    from jobs.repository import load_recent_jobs, persist_terminal

    j = Job(
        id="abc123",
        label="Test",
        operation="noop",
        target=None,
        status="done",
        progress=1.0,
        cost_estimate=0.01,
        cost_actual=0.02,
        started_at=100.0,
        ended_at=200.0,
    )
    j.log.append("line1")
    persist_terminal(j)

    restored = load_recent_jobs(10)
    assert any(x.id == "abc123" for x in restored)
    hit = next(x for x in restored if x.id == "abc123")
    assert hit.status == "done"
    assert "line1" in hit.log



"""Tests: users, sessions, costs, and job run persistence via the ORM."""

from __future__ import annotations

import pytest


def test_user_create_find_keys(isolated_repo):
    import users

    assert users.is_setup_required() is True
    u = users.create_first_user(email="a@example.com", password="password99", display_name="Ada")
    assert users.is_setup_required() is False
    assert users.find_by_email("a@example.com").id == u.id
    users.update_api_keys(u.id, pixellab_api_key="pk-test", openai_api_key="sk-test")
    again = users.find_by_id(u.id)
    assert again.pixellab_api_key == "pk-test"
    assert again.openai_api_key == "sk-test"
    pub = again.public_dict()
    assert pub["pixellab_api_key_set"] is True
    assert pub["openai_api_key_set"] is True


def test_session_cookie_roundtrip(isolated_repo):
    import sessions
    import users

    u = users.create_first_user(email="s@example.com", password="password99")
    cookie = sessions.create(u.id)
    assert sessions.resolve(cookie) == u.id
    assert sessions.resolve(cookie) == u.id  # sliding refresh
    sessions.destroy(cookie)
    assert sessions.resolve(cookie) is None


def test_register_user_second_account(isolated_repo):
    import users

    users.create_first_user(email="first@example.com", password="password99")
    u2 = users.register_user(email="second@example.com", password="password99", display_name="Two")
    assert users.find_by_email("second@example.com").id == u2.id
    assert u2.username


def test_register_user_rejects_duplicate_email(isolated_repo):
    import users

    users.create_first_user(email="same@example.com", password="password99")
    with pytest.raises(ValueError, match="already exists"):
        users.register_user(email="same@example.com", password="password99")


def test_create_first_user_still_single_setup(isolated_repo):
    import users

    users.create_first_user(email="only@example.com", password="password99")
    with pytest.raises(ValueError, match="closed"):
        users.create_first_user(email="other@example.com", password="password99")


def test_cost_ledger_summary(isolated_repo):
    import cost_ledger

    cost_ledger.record("gen.test", "space_a", 2, 0.05)
    s = cost_ledger.summary()
    assert s["lifetime_count"] >= 1
    assert s["lifetime_usd"] >= 0.05


def test_job_run_persist_reload(isolated_repo):
    import jobs
    from services.job_runs import load_recent_jobs, persist_terminal

    j = jobs.Job(
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


def test_backfill_owned_boards_assigns_unowned_to_first_user(isolated_repo):
    from boardfactory import boards as bf_boards
    from services import board_ownership as bo
    from users import create_first_user, find_by_email

    create_first_user(email="solo@example.com", password="password99", display_name="Solo")
    bf_boards.create_board("alpha", project_name="A")
    bf_boards.create_board("beta", project_name="B")

    bo.backfill_owned_boards_if_empty()

    u = find_by_email("solo@example.com")
    assert u is not None
    assert bo.user_owns_board(u.id, "alpha")
    assert bo.user_owns_board(u.id, "beta")

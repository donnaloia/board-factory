"""HTTP tests for side-panel cell metadata PATCH (e.g. space_kind)."""

from __future__ import annotations

from auth import services as auth_services
from server import app
from starlette.testclient import TestClient


def test_patch_space_kind(seeded_board, test_user):
    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    slug = seeded_board.id
    path = f"/users/{test_user.username}/board-games/{slug}/api/cell/spaces/corner_tl"
    r = client.patch(
        path,
        json={"space_kind": "event"},
        cookies={auth_services.COOKIE_NAME: sid},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spec"]["space_kind"] == "event"
    assert body["spec"]["id"] == "corner_tl"


def test_patch_space_kind_rejects_panels(seeded_board, test_user):
    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    slug = seeded_board.id
    path = f"/users/{test_user.username}/board-games/{slug}/api/cell/panels/panel_left_top"
    r = client.patch(
        path,
        json={"space_kind": "event"},
        cookies={auth_services.COOKIE_NAME: sid},
    )
    assert r.status_code == 400

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


def test_patch_space_metadata_requires_at_least_one_field(seeded_board, test_user):
    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    bid = seeded_board.id
    path = f"/users/{test_user.username}/board-games/{bid}/api/cell/spaces/corner_tl"
    r = client.patch(path, json={}, cookies={auth_services.COOKIE_NAME: sid})
    assert r.status_code == 400


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


def test_get_space_cell_includes_functional_targets(seeded_board, test_user):
    from domains.cells import repository as cells_repo

    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    bid = seeded_board.id
    panel_cell_id = cells_repo.find_id(bid, "panels", "panel_left_top")
    assert panel_cell_id
    path = f"/users/{test_user.username}/board-games/{bid}/api/cell/spaces/corner_tl"
    r = client.get(path, cookies={auth_services.COOKIE_NAME: sid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "functional_targets" in body
    ids = {x["cell_id"] for x in body["functional_targets"]}
    assert panel_cell_id in ids
    assert body.get("triggers_functional_cell_id") in (None, "")
    assert body.get("triggers_functional") is None


def test_patch_land_trigger_then_clear(seeded_board, test_user):
    from domains.cells import repository as cells_repo

    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    bid = seeded_board.id
    panel_cell_id = cells_repo.find_id(bid, "panels", "panel_left_top")
    assert panel_cell_id
    base = f"/users/{test_user.username}/board-games/{bid}/api/cell/spaces/corner_tl"

    r = client.patch(
        base,
        json={"triggers_functional_cell_id": panel_cell_id},
        cookies={auth_services.COOKIE_NAME: sid},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triggers_functional_cell_id"] == panel_cell_id
    assert body["triggers_functional"]["id"] == "panel_left_top"

    r2 = client.patch(
        base,
        json={"triggers_functional_cell_id": None},
        cookies={auth_services.COOKIE_NAME: sid},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json().get("triggers_functional_cell_id") in (None, "")


def test_patch_land_trigger_rejects_non_panel_target(seeded_board, test_user):
    from domains.cells import repository as cells_repo

    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    bid = seeded_board.id
    other_space_id = cells_repo.find_id(bid, "spaces", "corner_tr")
    assert other_space_id
    path = f"/users/{test_user.username}/board-games/{bid}/api/cell/spaces/corner_tl"
    r = client.patch(
        path,
        json={"triggers_functional_cell_id": other_space_id},
        cookies={auth_services.COOKIE_NAME: sid},
    )
    assert r.status_code == 400

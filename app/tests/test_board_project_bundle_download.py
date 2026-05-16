"""HTTP tests for ``GET …/export/project-bundle.zip`` (``domains.boards.exporter``)."""

from __future__ import annotations

import io
import zipfile

from auth import services as auth_services
from server import app
from starlette.testclient import TestClient


def test_project_bundle_zip_requires_auth(seeded_board, test_user):
    client = TestClient(app, follow_redirects=False)
    bid = seeded_board.id
    url = f"/users/{test_user.username}/board-games/{bid}/export/project-bundle.zip"
    r = client.get(url)
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert "/login" in loc or "/register" in loc


def test_project_bundle_zip_returns_zip(seeded_board, test_user):
    sid = auth_services.create_session_cookie(test_user.id)
    client = TestClient(app)
    bid = seeded_board.id
    url = f"/users/{test_user.username}/board-games/{bid}/export/project-bundle.zip"
    r = client.get(url, cookies={auth_services.COOKIE_NAME: sid})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert "attachment" in (r.headers.get("content-disposition") or "").lower()
    assert "project-export-" in (r.headers.get("content-disposition") or "")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "project.json" in names
    # ``assets/`` appears only when at least one live PNG was copied.
    assert len(names) >= 1

"""Protected website API: three separate steps, session checks, and one real practice run."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.settings import Settings
from backend.setup.browser import status
from backend.web_api import WebsiteJobs
from backend.web_journey import new_journey

from .support import ORIGIN, PORT, signed_in, visitor

REAL = Settings()


def external_scope() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "scope_id": "scope-1",
        "website_id": "website-1",
        "name": "Example shop",
        "mode": "external",
        "targets": [{"origin": "https://shop.example.com", "paths": ["/"]}],
        "purpose": "Check the public pages.",
        "authority": {
            "granted_by": "Owner",
            "reference": "Ticket 1",
            "granted_at": (now - timedelta(minutes=1)).isoformat(),
        },
        "allowed_actions": ["read", "report"],
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "stop_conditions": ["Unexpected personal data appears."],
        "confirmed_targets": True,
    }


def test_restarted_human_handoff_exposes_the_continue_form(tmp_path: Path) -> None:
    from backend.contracts.web import WebsiteScope

    settings = Settings(data_dir=tmp_path)
    jobs = WebsiteJobs(settings)
    view = new_journey(settings, WebsiteScope.model_validate(external_scope()))
    jobs.store.save(view.model_copy(update={"status": "handoff"}))
    restarted = jobs.read(view.journey_id)
    assert restarted.status == "paused" and "previous worker stopped" in str(restarted.stop_reason)
    assert jobs.human_view(view.journey_id) is None


@pytest.fixture
def connected(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    app = create_app(Settings(data_dir=tmp_path / "private"), port=PORT)
    with signed_in(app) as client:
        client.headers["origin"] = ORIGIN
        yield app, client


def test_scope_plan_approval_and_run_are_separate_and_nothing_external_runs_unqualified(
    connected: tuple[FastAPI, TestClient],
) -> None:
    _, client = connected
    assert client.get("/api/websites").json() == {"journeys": []}
    readiness = client.get("/api/websites/readiness").json()
    assert readiness["external_ready"] is False and "qualif" in readiness["external_note"]
    created = client.post(
        "/api/websites", json={"scope": external_scope(), "confirmed_authority": True}
    )
    assert created.status_code == 200, created.text
    view = created.json()
    assert view["status"] == "planned" and view["spent"]["requests"] == 0
    journey = view["journey_id"]
    # Not approved: it cannot run.
    assert client.post(f"/api/websites/{journey}/run", json={}).status_code == 409
    assert (
        client.post(
            f"/api/websites/{journey}/approve",
            json={"plan_sha256": "0" * 64, "approved_by": "R", "reviewed_plan": True},
        ).status_code
        == 409
    )
    plan_hash = None
    for candidate in (view["plan"],):
        from backend.contracts.web import WebsitePlan

        plan_hash = WebsitePlan.model_validate(candidate).sha256
    approved = client.post(
        f"/api/websites/{journey}/approve",
        json={"plan_sha256": plan_hash, "approved_by": "Reviewer", "reviewed_plan": True},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    started = client.post(f"/api/websites/{journey}/run", json={"use_model": False})
    assert started.status_code == 202
    for _ in range(200):
        current = client.get(f"/api/websites/{journey}").json()
        if current["status"] != "running":
            break
        time.sleep(0.05)
    # The boundary is not qualified in this empty data folder: nothing was sent anywhere.
    assert current["status"] == "stopped" and "qualif" in current["stop_reason"]
    assert current["spent"]["requests"] == 0 and current["pages"] == []
    assert client.post(f"/api/websites/{journey}/revoke").json()["approval_revoked_at"]


def test_bad_scopes_and_requests_are_refused_without_echo(
    connected: tuple[FastAPI, TestClient],
) -> None:
    app, client = connected
    for change in (
        {"confirmed_targets": False},
        {"targets": [{"origin": "http://shop.example.com", "paths": ["/"]}]},
        {"targets": [{"origin": "https://127.0.0.1", "paths": ["/"]}]},
        {"targets": [{"origin": "https://user:pw@shop.example.com", "paths": ["/"]}]},
        {"targets": [{"origin": "https://shop.example.com", "paths": ["/a/../b"]}]},
        {"allowed_actions": ["read", "compare"]},
        {"expires_at": "2020-01-01T00:00:00+00:00"},
    ):
        response = client.post(
            "/api/websites",
            json={"scope": {**external_scope(), **change}, "confirmed_authority": True},
        )
        assert response.status_code in {409, 422}, change
        assert "user:pw" not in response.text
    assert client.post("/api/websites", json={"scope": external_scope()}).status_code == 422
    assert client.get("/api/websites/journey-nope").status_code == 409
    assert client.get("/api/websites/journey-" + "a" * 32).status_code == 409
    guest = visitor(app)
    for method, path in (
        ("GET", "/api/websites"),
        ("GET", "/api/websites/readiness"),
        ("POST", "/api/websites"),
        ("POST", "/api/websites/fixture"),
    ):
        assert guest.request(method, path, headers={"origin": ORIGIN}, json={}).status_code == 401
        assert (
            client.request(
                method, path, headers={"origin": "https://external.invalid"}, json={}
            ).status_code
            == 403
        )


@pytest.mark.browser
@pytest.mark.skipif(not status(REAL)["verified"], reason="pinned browser not provisioned")
def test_the_practice_site_runs_end_to_end_through_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The journey record lives in a private temporary folder; the browser is the provisioned one.
    settings = Settings(data_dir=tmp_path / "private")
    monkeypatch.setattr("backend.setup.browser.directory", lambda _: REAL.data_dir / "browsers")
    app = create_app(settings, port=PORT)
    with signed_in(app) as client:
        client.headers["origin"] = ORIGIN
        assert client.get("/api/websites/readiness").json()["browser_ready"] is True
        view = client.post("/api/websites/fixture", json={"variant": "defended"}).json()
        journey = view["journey_id"]
        from backend.contracts.web import WebsitePlan

        client.post(
            f"/api/websites/{journey}/approve",
            json={
                "plan_sha256": WebsitePlan.model_validate(view["plan"]).sha256,
                "approved_by": "Reviewer",
                "reviewed_plan": True,
            },
        )
        assert (
            client.post(f"/api/websites/{journey}/run", json={"use_model": False}).status_code
            == 202
        )
        assert client.post(f"/api/websites/{journey}/run", json={}).status_code == 409  # one worker
        for _ in range(900):
            current = client.get(f"/api/websites/{journey}").json()
            if current["status"] != "running":
                break
            time.sleep(0.1)
        assert current["status"] == "paused", current["stop_reason"]  # waits for one answer
        subject = current["waiting"][0]["subject"]
        client.post(
            f"/api/websites/{journey}/run",
            json={"use_model": False, "answers": {subject: "display_name"}},
        )
        for _ in range(900):
            current = client.get(f"/api/websites/{journey}").json()
            if current["status"] != "running":
                break
            time.sleep(0.1)
        assert current["status"] == "done", current["stop_reason"]
        assert current["findings"] == [] and len(current["checks"]) == 4
        report = client.get(f"/api/websites/{journey}/report")
        assert report.status_code == 200 and "0 supported finding(s)" in report.text
        assert report.headers["cache-control"] == "no-store"

"""Real contained OTP/CAPTCHA interaction on the explicit owned loopback seam.

The human's clicks and answers are scripted fixture inputs, never model quality.
No external website or third-party challenge is used or bypassed.
"""

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from backend.contracts.web import WebTarget
from backend.contracts.web_journey import HumanAuthInput, JourneyApprove
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.browser import status
from backend.web_human import HumanChannel
from backend.web_journey import Journey, new_journey
from backend.web_plan import approve
from backend.web_store import JourneyStore
from verification.egress import ActionPermission, Egress, EgressPolicy
from verification.web_browser import BrowserRunner
from verification.web_http import HttpAdapter
from verification.web_seam import Hit, Site, budget
from verification.web_secrets import SecretStore

from .test_web_scope import scope

REAL = Settings()
pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not status(REAL)["verified"], reason="pinned browser not provisioned"),
]


@pytest.mark.parametrize("challenge", ["one_time_code", "captcha"])
def test_real_human_challenge_restores_isolation_and_explicitly_confirms(
    tmp_path: Path, challenge: str
) -> None:
    code = "738291"
    field = "otp" if challenge == "one_time_code" else "captcha_text"
    title = "One-time code" if challenge == "one_time_code" else "CAPTCHA practice challenge"
    html = (
        f"<h1>{title}</h1><p>Enter the practice answer shown by the test owner.</p>"
        f'<form action="/challenge" method="post"><label for="answer">{title}</label>'
        f'<input id="answer" type="text" name="{field}" autocomplete="one-time-code" '
        'style="position:absolute;left:40px;top:100px;width:360px;height:40px" required>'
        '<button type="submit" style="position:absolute;left:40px;top:170px">'
        "Continue</button></form>"
    ).encode()

    def challenge_route(hit: Hit) -> tuple[int, dict[str, str], bytes]:
        if hit.method == "POST":
            assert hit.body == f"{field}={code}".encode()
            return (
                302,
                {
                    "Location": "/signed-in",
                    "Set-Cookie": "auth=X9g7U2r8L1m6F5w3K4b0Q7h2; Path=/",
                },
                b"",
            )
        return (
            200,
            {
                "Content-Type": "text/html",
                "Set-Cookie": "pending=H4j8N2t6V1s9C7p3Z5e0A2u4; Path=/",
            },
            html,
        )

    def signed_in(hit: Hit) -> tuple[int, dict[str, str], bytes]:
        if "auth=X9g7U2r8L1m6F5w3K4b0Q7h2" in hit.headers.get("cookie", ""):
            return 200, {"Content-Type": "text/html"}, b"<h1>Signed in as designated Anna</h1>"
        return 200, {"Content-Type": "text/html"}, html

    site = Site({"/challenge": challenge_route, "/signed-in": signed_in})
    settings = Settings(data_dir=tmp_path)
    approved_scope = scope(
        mode="owned_fixture",
        targets=[WebTarget(origin=site.origin, paths=["/"])],
        start_path="/challenge",
        allowed_actions=["sign_in", "report"],
        login={
            "path": "/challenge",
            "success_path": "/signed-in",
            "success_text": "Signed in as designated Anna",
        },
    )
    view = new_journey(settings, approved_scope)
    view = approve(
        view,
        JourneyApprove(
            plan_sha256=view.plan_sha256, approved_by="Fixture owner", reviewed_plan=True
        ),
    )
    JourneyStore(settings).save(view)
    secrets = SecretStore()
    journey = Journey(settings, view.journey_id, secrets=secrets)
    channel = HumanChannel()
    broker = Egress(
        EgressPolicy(
            mode="owned_fixture",
            targets=tuple(approved_scope.targets),
            expires_at=approved_scope.expires_at,
            owned_port=site.port,
            approved_actions=(ActionPermission("signin-anna", "sign_in", "anna"),),
        ),
        budget(requests=100, size=10_000_000, seconds=90),
    )
    failure: list[Exception] = []

    def human() -> None:
        try:
            deadline = time.monotonic() + 50
            while channel.snapshot() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("the private view was not published")
                time.sleep(0.05)
            for kind in ("pointer", "text", "submit", "completed"):
                current = channel.snapshot()
                assert current is not None
                event = {"view_id": current.view_id, "kind": kind}
                if kind == "pointer":
                    event.update(x=70, y=120)
                if kind == "text":
                    event["text"] = code
                channel.send(HumanAuthInput.model_validate(event), seconds=20)
        except Exception as error:
            failure.append(error)
            journey.cancel.set()

    try:
        with BrowserRunner(
            REAL, broker, secrets=secrets, redactor=Redactor(), expected_personal=journey.expected
        ) as first:
            first.navigate("anna", journey.url("/challenge"))
            if challenge == "one_time_code":
                journey.set_step("signin-anna", "attempted")
            journey.handoff(
                journey.plan["signin-anna"],
                journey.accounts["anna"],
                challenge,
                first,
                HttpAdapter(broker),
            )
        assert journey.view.waiting and journey.store.session(view.journey_id, "anna")
        journey = Journey(
            settings,
            view.journey_id,
            secrets=secrets,
            human=channel,
            answers={"human:signin-anna": "resume"},
        )
        journey.take_answers()
        journey._egress, journey._started = broker, time.monotonic()
        driver = threading.Thread(target=human, daemon=True)
        driver.start()
        with BrowserRunner(
            REAL, broker, secrets=secrets, redactor=Redactor(), expected_personal=journey.expected
        ) as resumed:
            journey.resume_handoffs(resumed, HttpAdapter(broker))
            assert resumed.session("boris").cookies == {}
        driver.join(timeout=5)
        assert not failure and not driver.is_alive()
        assert journey.account_state("anna") == "signed_in"
        assert journey.step("signin-anna").state == "completed" and journey.view.waiting == []
        assert sum(hit.method == "POST" for hit in site.hits) == 1
        saved = JourneyStore(settings).load(view.journey_id).model_dump_json()
        assert code not in saved and "screenshot_png" not in saved
        assert channel.snapshot() is None
    finally:
        channel.close()
        broker.close()
        site.close()

"""Qualifying the egress boundary before any external website may be visited (ADR-0028).

External mode stays refused until a qualification record exists for exactly the
current boundary code and browser pin, and that record passed. The record comes
from running the real pinned browser against Plumb's own fixture and stand-ins:
a page that tries every way to leave its scope must reach nothing.

    uv run --extra browser plumb website qualify

Passing enables explicitly approved external origins through this adapter. It
starts no external test: each one still needs its own confirmed scope.
"""

import hashlib
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.contracts.web import WebTarget
from backend.redaction import Redactor
from backend.settings import Settings
from backend.web_urls import parse_url

REPOSITORY = Path(__file__).resolve().parents[1]
RECORD = "boundary-qualification.json"
# The code and pins that make up the boundary. Any change to them needs a new qualification.
FILES = (
    "backend/web_urls.py",
    "backend/setup/pins/browser.toml",
    "verification/egress.py",
    "verification/web_proxy.py",
    "verification/web_browser.py",
    "verification/web_human.py",
    "verification/web_pages.py",
    "verification/web_http.py",
    "verification/web_tls.py",
)


def implementation() -> str:
    digest = hashlib.sha256()
    for name in FILES:
        digest.update(name.encode())
        digest.update(hashlib.sha256((REPOSITORY / name).read_bytes()).digest())
    return digest.hexdigest()


def record_path(settings: Settings) -> Path:
    return settings.data_dir / "websites" / RECORD


def qualified(settings: Settings) -> str | None:
    """None when external websites may be visited; otherwise the plain reason they may not."""
    try:
        record = json.loads(record_path(settings).read_bytes())
    except (OSError, ValueError):
        return (
            "External websites stay disabled until the network boundary is qualified on this "
            "computer. Run: plumb website qualify"
        )
    if not isinstance(record, dict) or record.get("passed") is not True:
        return "The last boundary qualification did not pass; external websites stay disabled."
    if record.get("implementation_sha256") != implementation():
        return (
            "The boundary code or browser pin changed since it was qualified. "
            "Run: plumb website qualify"
        )
    return None


def qualify(settings: Settings) -> dict[str, Any]:
    """Run the boundary checks with the real browser and save the record, pass or fail."""
    from verification.egress import (
        Egress,
        EgressPolicy,
        EgressRefused,
        public_address,
        tls_context,
    )
    from verification.web_browser import BrowserRunner
    from verification.web_fixture import SUPPORT, launch
    from verification.web_seam import PUBLIC, Canary, Site, budget, carried, soon, tls_for
    from verification.web_secrets import SecretStore

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail[:300]})

    started = time.monotonic()
    error: str | None = None
    canary = Canary()
    try:
        inward = ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1", "::ffff:10.0.0.1"]
        check(
            "non-public addresses are refused in external mode",
            all(public_address(a) is not None for a in inward)
            and public_address("8.8.8.8") is None,
        )
        with launch("open", settings, port=0, boundary=canary.port) as fixture:
            scope = fixture.scope()
            egress = Egress(
                EgressPolicy(
                    mode="owned_fixture",
                    targets=tuple(scope.targets),
                    expires_at=scope.expires_at,
                    owned_port=fixture.port,
                ),
                budget(requests=400, size=30_000_000, seconds=180),
            )
            try:
                with BrowserRunner(
                    settings,
                    egress,
                    secrets=SecretStore(),
                    redactor=Redactor.configured(settings),
                    expected_personal=frozenset({SUPPORT}),
                ) as browser:
                    check("the browser's own sandbox is on", browser.sandboxed())
                    browser.navigate(None, parse_url(fixture.origin + "/boundary/escape"))
                    text, deadline = "", time.monotonic() + 30
                    while time.monotonic() < deadline and "finished" not in text:
                        text = browser.observe(None).observation.text
                        time.sleep(0.25)
                    time.sleep(1.5)
                    check("the escape page ran to its end", "finished" in text)
                    check(
                        "nothing reached the listener outside the scope",
                        canary.connections == 0,
                        f"{canary.connections} connection(s)",
                    )
                    check(
                        "every request went to the approved origin",
                        {r.origin for r in egress.records} == {fixture.origin},
                    )
                    kinds = {row.kind for row in egress.blocked}
                    check(
                        "off-scope, redirect and WebSocket attempts are on record as refused",
                        {"off_scope", "redirect", "websocket"} <= kinds,
                        ", ".join(sorted(kinds)),
                    )
                    check(
                        "no service worker script was fetched",
                        "/boundary/sw.js" not in {r.path for r in egress.records},
                    )
                    refused = 0
                    for address in (
                        f"http://127.0.0.1:{canary.port}/direct",
                        f"http://localhost:{fixture.port}/",
                        "https://example.com/",
                    ):
                        try:
                            browser.navigate(None, parse_url(address))
                        except EgressRefused:
                            refused += 1
                    check("direct off-scope navigation is refused before any request", refused == 3)
                    status = browser.navigate(
                        None, parse_url(fixture.origin + "/boundary/redirect")
                    )
                    check("a top-level redirect out of scope ends at the broker", status == 403)
                    time.sleep(0.5)
                    check("still nothing reached the outside listener", canary.connections == 0)
            finally:
                egress.close()
        # HTTPS through the broker's own front, and the external-mode address checks.
        with tempfile.TemporaryDirectory(dir=settings.cache_dir) as folder:
            material = tls_for("shop.test", Path(folder))
            site = Site(
                {
                    "/": (
                        200,
                        {"Content-Type": "text/html"},
                        b"<title>Secure</title><h1>Secure</h1>"
                        b"<img src='https://tracker.test/p.png'>",
                    )
                },
                context=material.server,
            )
            try:

                def external(
                    answers: list[str], report: str | None = None, trust: bool = True
                ) -> Egress:
                    return Egress(
                        EgressPolicy(
                            mode="external",
                            targets=(WebTarget(origin="https://shop.test", paths=["/"]),),
                            expires_at=soon(),
                        ),
                        budget(),
                        resolver=lambda name, port: list(answers),
                        connect=carried(site.port, report=report),
                        context=tls_context(material.authority_pem if trust else None),
                    )

                def reaches(egress: Egress) -> bool:
                    try:
                        egress.send("GET", parse_url("https://shop.test/"), []).read(100_000)
                        return True
                    except EgressRefused:
                        return False
                    finally:
                        egress.close()

                check(
                    "a public name with a valid certificate is reached", reaches(external([PUBLIC]))
                )
                check(
                    "a name that resolves inward is refused",
                    not reaches(external([PUBLIC, "10.0.0.7"]))
                    and not reaches(external(["127.0.0.1"])),
                )
                check(
                    "a connection that lands elsewhere is dropped",
                    not reaches(external([PUBLIC], report="203.0.113.9")),
                )
                check(
                    "an untrusted certificate is refused",
                    not reaches(external([PUBLIC], trust=False)),
                )
                hits_before = len(site.hits)
                broker = external([PUBLIC])
                try:
                    with BrowserRunner(
                        settings,
                        broker,
                        secrets=SecretStore(),
                        redactor=Redactor.configured(settings),
                        expected_personal=frozenset(),
                    ) as browser:
                        status = browser.navigate(None, parse_url("https://shop.test/"))
                        title = browser.observe(None).observation.title
                        check(
                            "an HTTPS page loads through the broker's inspected front",
                            status == 200 and title == "Secure" and len(site.hits) > hits_before,
                        )
                        check(
                            "the page's off-scope HTTPS dependency was refused and recorded",
                            ("off_scope", "tracker.test")
                            in {(row.kind, row.host) for row in broker.blocked},
                        )
                finally:
                    broker.close()
            finally:
                site.close()
    except Exception as failure:
        error = Redactor.configured(settings).text(f"{type(failure).__name__}: {failure}")[:600]
    finally:
        canary.close()
    passed = error is None and bool(checks) and all(item["passed"] for item in checks)
    record = {
        "passed": passed,
        "at": datetime.now(UTC).isoformat(),
        "seconds": round(time.monotonic() - started, 2),
        "implementation_sha256": implementation(),
        "files": list(FILES),
        "checks": checks,
        "error": error,
        "guarantee": "Page content cannot make this browser reach an address outside the frozen "
        "scope: the broker is its only network path and decides every connection.",
        "limits": "Not a defence against a browser exploit that escapes Chromium's sandbox, nor "
        "against other software on this computer.",
    }
    path = record_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return record

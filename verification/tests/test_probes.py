"""Oracle and transport boundaries; no application code or real network runs."""

from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from backend.contracts.verification import (
    Access,
    HTTPProbeRequest,
    ProbeOutcome,
    ProbeRun,
    ProbeSpec,
    RunnerKind,
    SnapshotRole,
    StepRole,
)
from verification.probes import execute

MARKER = "OWNER_MARKER_123"


def spec() -> ProbeSpec:
    return ProbeSpec(
        id="probe:receipt",
        finding_id="finding:receipt",
        marker=MARKER,
        requests=[
            HTTPProbeRequest(
                role=role,
                principal=user,
                method="GET",
                path="/orders/1/receipt",
                expected_if_safe=expected,
            )
            for role, user, expected in [
                (StepRole.ATTACK, "bob", Access.DENIED),
                (StepRole.CONTROL, "alice", Access.ALLOWED),
            ]
        ],
    )


def run(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    patched: bool = False,
    probe: ProbeSpec | None = None,
) -> ProbeRun:
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        return execute(
            probe or spec(),
            client=client,
            origin="http://127.0.0.1:8701",
            headers={"alice": {"x-principal": "alice"}, "bob": {"x-principal": "bob"}},
            snapshot_id="1" * 64,
            manifest_sha256="2" * 64,
            runner=RunnerKind.BUNDLED_LAB,
            snapshot_role=SnapshotRole.PATCHED if patched else SnapshotRole.VULNERABLE,
            run_id="probe-run:test",
        )


@pytest.mark.parametrize(
    "control_status,body", [(500, MARKER), (403, "denied"), (200, "no victim"), (302, "")]
)
def test_vacuous_control_cannot_reproduce_or_fix(control_status: int, body: str) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(control_status, text=body)
            if request.headers["x-principal"] == "alice"
            else httpx.Response(200, text=MARKER)
        )

    assert run(answer).outcome is ProbeOutcome.INCONCLUSIVE
    assert run(answer, patched=True).outcome is ProbeOutcome.INCONCLUSIVE


def test_attack_and_control_both_succeed_before_reproduction() -> None:
    assert run(lambda r: httpx.Response(200, text=MARKER)).outcome is ProbeOutcome.REPRODUCED


def test_fixed_means_denied_attack_and_preserved_owner_access() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404, text="missing")
            if request.headers["x-principal"] == "bob"
            else httpx.Response(200, text=MARKER)
        )

    assert run(answer, patched=True).outcome is ProbeOutcome.FIXED
    assert run(answer).outcome is ProbeOutcome.NOT_REPRODUCED


@pytest.mark.parametrize("status", [500, 400, 302])
def test_errors_or_redirects_never_prove_a_fix(status: int) -> None:
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return (
            httpx.Response(status, headers={"location": "https://example.com"})
            if request.headers["x-principal"] == "bob"
            else httpx.Response(200, text=MARKER)
        )

    assert run(answer, patched=True).outcome is ProbeOutcome.INCONCLUSIVE
    assert len(seen) == 2
    assert all(url.startswith("http://127.0.0.1:8701/") for url in seen)


def test_timeout_and_oversized_response_do_not_promote() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("not recorded", request=request)

    assert run(timeout).outcome is ProbeOutcome.INCONCLUSIVE
    assert (
        run(lambda r: httpx.Response(200, content=b"x" * 65537)).outcome
        is ProbeOutcome.INCONCLUSIVE
    )


@pytest.mark.parametrize(
    "path", ["//example.com/", "https://example.com/", "/\\example.com", "/x#hidden", "/x\nheader"]
)
def test_paths_cannot_select_other_hosts_or_smuggle_headers(path: str) -> None:
    with pytest.raises(ValidationError):
        HTTPProbeRequest(
            role=StepRole.ATTACK,
            principal="bob",
            method="GET",
            path=path,
            expected_if_safe=Access.DENIED,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:8701",
        "http://localhost:8701",
        "http://192.168.1.1:8701",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:8701/escape",
    ],
)
def test_origins_are_exact_loopback_only(origin: str) -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: pytest.fail("network must not run"))
        ) as client,
        pytest.raises(ValueError),
    ):
        execute(
            spec(),
            client=client,
            origin=origin,
            headers={},
            snapshot_id="1" * 64,
            manifest_sha256="2" * 64,
            runner=RunnerKind.BUNDLED_LAB,
            snapshot_role=SnapshotRole.VULNERABLE,
            run_id="probe-run:test",
        )


def test_capture_requires_successful_setup_and_a_numeric_id() -> None:
    setup = HTTPProbeRequest(
        role=StepRole.SETUP,
        principal="alice",
        method="POST",
        path="/orders",
        body={"delivery_address": "{marker}"},
        capture={"order_id": "id"},
        expected_if_safe=Access.ALLOWED,
    )
    probe = spec().model_copy(
        update={
            "requests": [
                setup,
                *[
                    r.model_copy(update={"path": "/orders/{order_id}/receipt"})
                    for r in spec().requests
                ],
            ]
        }
    )
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return (
            httpx.Response(201, json={"id": 17})
            if request.method == "POST"
            else httpx.Response(200, text=MARKER)
        )

    assert run(answer, probe=probe).outcome is ProbeOutcome.REPRODUCED
    assert seen[-1].url.path == "/orders/17/receipt"
    assert (
        run(lambda r: httpx.Response(201, json={"id": "../../escape"}), probe=probe).outcome
        is ProbeOutcome.INCONCLUSIVE
    )
    assert run(lambda r: httpx.Response(500), probe=probe).outcome is ProbeOutcome.INCONCLUSIVE


def test_attack_without_control_is_not_a_probe_spec() -> None:
    with pytest.raises(ValidationError, match="attack and control"):
        ProbeSpec.model_validate({**spec().model_dump(), "requests": [spec().requests[0]] * 2})

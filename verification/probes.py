"""Bounded declarative HTTP transport and the attack/control oracle (§3.4)."""

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import JsonValue

from backend.contracts.verification import (
    ProbeRun,
    ProbeSpec,
    ProbeStep,
    RunnerKind,
    SnapshotRole,
    StepRole,
    derive_outcome,
)

MAX_RESPONSE = 65536
VARIABLE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def substitute(text: str, variables: Mapping[str, str], *, path: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        value = variables[match[1]]
        return quote(value, safe="") if path else value

    value = VARIABLE.sub(replace, text)
    if "{" in value or "}" in value:
        raise ValueError("unsupported template syntax")
    return value


def body_value(value: JsonValue, variables: Mapping[str, str]) -> JsonValue:
    if isinstance(value, str):
        return substitute(value, variables)
    if isinstance(value, list):
        return [body_value(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: body_value(v, variables) for k, v in value.items()}
    return value


def execute(
    spec: ProbeSpec,
    *,
    client: httpx.Client,
    origin: str,
    headers: Mapping[str, Mapping[str, str]],
    snapshot_id: str,
    manifest_sha256: str,
    runner: RunnerKind,
    snapshot_role: SnapshotRole,
    run_id: str,
) -> ProbeRun:
    """Caller must first verify its runner and approve this spec for that runner.

    No redirects, environment proxies, shell, response code execution or body logs.
    Tests inject MockTransport. The bundled runner supplies a loopback-only client.
    """
    if re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", origin) is None:
        raise ValueError("probe origin must be explicit IPv4 loopback")
    if not 1 <= int(origin.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("invalid probe port")
    started = datetime.now(UTC)
    steps: list[ProbeStep] = []
    variables = {"marker": spec.marker}
    for request in spec.requests:
        status, present, error = None, None, None
        path = request.path
        try:
            path = substitute(path, variables, path=True)
            auth = headers[request.principal]
            payload = body_value(request.body, variables)
            if len(json.dumps(payload, allow_nan=False).encode()) > MAX_RESPONSE:
                raise ValueError("probe body exceeds transport budget")
            data = bytearray()
            with client.stream(
                request.method,
                origin + path,
                headers=auth,
                json=payload,
                follow_redirects=False,
                timeout=5,
            ) as response:
                status = response.status_code
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise ValueError("probe response exceeds transport budget")
            present = spec.marker.encode() in data
            if request.capture:
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError("capture requires a JSON object")
                for name, field in request.capture.items():
                    item = parsed[field]
                    if (
                        re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
                        or type(item) is not int
                        or not 0 < item < 2**53
                    ):
                        raise ValueError("only positive integer identifiers can be captured")
                    variables[name] = str(item)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Deliberately omit credentials, URLs, response bodies and exception details.
            present, error = None, "Transport, template, capture or response budget failed"
        steps.append(
            ProbeStep(
                role=request.role,
                principal=request.principal,
                method=request.method,
                path=path,
                expected_if_safe=request.expected_if_safe,
                status=status,
                marker_present=present,
                error=error,
            )
        )
        if request.role is StepRole.SETUP and (error or status is None or not 200 <= status < 300):
            break
    return ProbeRun(
        id=run_id,
        finding_id=spec.finding_id,
        runner=runner,
        runner_manifest_sha256=manifest_sha256,
        snapshot_id=snapshot_id,
        snapshot_role=snapshot_role,
        steps=steps,
        outcome=derive_outcome(snapshot_role, steps),
        started_at=started,
        finished_at=datetime.now(UTC),
    )

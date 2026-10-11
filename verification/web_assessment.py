"""Explicitly approved HTTP collection from the hash-pinned owned Tandir only.

No browser, redirects, subresources, arbitrary target processes or external
network targets are available. Every request, including fixture authentication
and creation, appears in a reviewed preview before the trusted lab starts.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from uuid import uuid4

import httpx
from pydantic import JsonValue

from backend.assessment import (
    SensitiveDiscovery,
    sanitize_observation_body,
    sanitize_observation_headers,
)
from backend.contracts.assessment import AssessmentScope, normalized_path
from backend.contracts.assessment_engine import (
    ControlledHTTPAction,
    ControlledHTTPPermission,
    ControlledHTTPPreview,
    ControlledHTTPResult,
    HTTPActionProgress,
)
from backend.contracts.verification import ProbeSpec
from backend.redaction import Redactor
from backend.settings import Settings
from verification import lab
from verification.owned_http import PinnedLoopbackTransport, runtime_port
from verification.probes import MAX_RESPONSE, body_value, substitute

DECLARED_ORIGIN = "http://127.0.0.1:8701"
RESPONSE_HEADERS = frozenset({"date", "server", "content-length", "content-type"})


class CollectionStopped(ValueError):
    pass


@dataclass
class CollectionBytes:
    maximum: int
    received: int = 0

    def charge(self, count: int) -> None:
        self.received += count
        if self.received > self.maximum:
            raise CollectionStopped("aggregate response byte budget exhausted")


def _collected_headers(headers: Mapping[str, str], redactor: Redactor) -> None:
    """The fixed owned fixture admits only its small, nonpersonal metadata surface."""
    if any(name.lower() not in RESPONSE_HEADERS for name in headers):
        raise CollectionStopped("unexpected response header; stopped for private incident review")
    try:
        sanitized = sanitize_observation_headers(dict(headers), redactor)
    except SensitiveDiscovery:
        raise CollectionStopped(
            "unexpected personal response metadata; stopped for private incident review"
        ) from None
    for name, value in sanitized.items():
        if name == "server":
            valid = value == "uvicorn"
        elif name == "content-length":
            valid = re.fullmatch(r"[0-9]{1,5}", value) is not None and int(value) <= MAX_RESPONSE
        elif name == "content-type":
            valid = (
                re.fullmatch(
                    r"(?:application/json|text/plain|text/html)(?:; charset=utf-8)?",
                    value,
                    flags=re.IGNORECASE,
                )
                is not None
            )
        else:
            try:
                parsed = parsedate_to_datetime(value)
                valid = parsed.tzinfo == UTC and format_datetime(parsed, usegmt=True) == value
            except (ValueError, TypeError, OverflowError):
                valid = False
        if not valid:
            raise CollectionStopped(
                "unexpected response metadata; stopped for private incident review"
            )


def _collected_body(text: str, redactor: Redactor, marker: str) -> str:
    """Minimize pinned fixture metadata, stopping on unexpected personal fields."""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and "customer_name" in parsed:
        if parsed["customer_name"] != "Alice Karimova":
            raise CollectionStopped("unexpected personal name; stopped for private incident review")
        # This fixed fixture name is not necessary for marker-based comparisons.
        parsed = {key: value for key, value in parsed.items() if key != "customer_name"}
        text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    try:
        return sanitize_observation_body(text, redactor, (marker,))
    except SensitiveDiscovery:
        raise CollectionStopped(
            "unexpected personal information; stopped for private incident review"
        ) from None


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _scope_hash(scope: AssessmentScope) -> str:
    return _hash(scope.model_dump(mode="json"))


def _scope_path(scope: AssessmentScope, path: str) -> None:
    normalized_path(path)
    if not any(
        path == allowed or path.startswith(allowed.rstrip("/") + "/")
        for allowed in scope.allowed_paths
    ):
        raise ValueError("request path lies outside reviewed scope")


def validate_runtime_origin(origin: str) -> None:
    runtime_port(origin)


def _validate_scope(scope: AssessmentScope, now: datetime) -> None:
    scope = AssessmentScope.model_validate(scope.model_dump())
    if now >= scope.expires_at or now < scope.authority.granted_at:
        raise ValueError("assessment scope expired")
    if scope.application_id != "owned-tandir" or scope.origin != DECLARED_ORIGIN:
        raise ValueError("external website interaction is disabled; only owned Tandir is admitted")
    if not {"read", "collect", "authenticate", "create_synthetic"}.issubset(scope.allowed_actions):
        raise ValueError(
            "scope must explicitly permit authentication, synthetic creation and collection"
        )
    if {account.account_id for account in scope.accounts} != {"alice", "bob"}:
        raise ValueError("runner only uses the designated alice/bob synthetic fixture accounts")
    if any(account.role != "customer" for account in scope.accounts):
        raise ValueError("declared roles must match the hash-pinned customer fixtures")
    _scope_path(scope, "/auth/login")
    _scope_path(scope, "/orders")
    _scope_path(scope, "/health")


def _actions(spec: ProbeSpec, control_spec: ProbeSpec | None = None) -> list[ControlledHTTPAction]:
    actions = [
        ControlledHTTPAction(
            action_id="readiness:health",
            account_id=None,
            method="GET",
            path="/health",
            purpose="readiness",
            max_attempts=4,
            state_change=False,
        )
    ]
    actions.extend(
        [
            ControlledHTTPAction(
                action_id="authenticate:" + account,
                account_id=account,
                method="POST",
                path="/auth/login",
                purpose="authenticate",
                body_preview={
                    "username": account,
                    "credential_source": "pinned synthetic fixture; kept outside evidence",
                },
                state_change=True,
            )
            for account in ("alice", "bob")
        ]
    )
    requests = [
        *spec.requests,
        *(control_spec.requests[1:] if control_spec else []),
        *([control_spec.requests[1]] if control_spec else []),
    ]
    for index, request in enumerate(requests):
        if request.principal not in {"alice", "bob"}:
            raise ValueError("only reviewed synthetic principals are admitted")
        actions.append(
            ControlledHTTPAction(
                action_id=f"probe:{index}",
                account_id=request.principal,
                method=request.method,
                path=request.path,
                purpose="create_synthetic" if index == 0 else "read",
                body_preview=request.body,
                state_change=index == 0,
            )
        )
    return actions


def preview_lab_assessment(
    scope: AssessmentScope,
    *,
    invoice: bool = False,
    paired: bool = False,
    synthetic_object_id: str | None = None,
) -> ControlledHTTPPreview:
    now = datetime.now(UTC)
    _validate_scope(scope, now)
    if paired and invoice:
        raise ValueError("paired preview always compares receipt with its invoice control")
    objects = [
        item
        for item in scope.synthetic_objects
        if item.owner_account_id == "alice"
        and item.synthetic_marker
        and (synthetic_object_id is None or item.object_id == synthetic_object_id)
    ]
    if len(objects) != 1:
        raise ValueError(
            "preview requires one designated synthetic alice object with an exact marker"
        )
    item = objects[0]
    if item.synthetic_marker is None:
        raise ValueError("synthetic marker is required")
    if Redactor.configured().text(item.synthetic_marker) != item.synthetic_marker:
        raise ValueError("a synthetic marker cannot contain credential material")
    spec = lab.receipt_spec(item.synthetic_marker, invoice=invoice)
    lab.admit(spec)
    control_spec = lab.receipt_spec(item.synthetic_marker, invoice=True) if paired else None
    if control_spec:
        lab.admit(control_spec)
    _, manifest = lab.verified_files()
    # The trusted fixture creates an integer ID. Scope the whole reviewed orders
    # collection; path placeholders never broaden the fixed admitted template.
    _scope_path(scope, "/orders/{order_id}/" + ("invoice" if invoice else "receipt"))
    if paired:
        _scope_path(scope, "/orders/{order_id}/invoice")
    actions = _actions(spec, control_spec)
    request_cap = sum(action.max_attempts for action in actions)
    if scope.budget.max_requests < request_cap:
        raise ValueError("scope budget cannot cover the explicitly reviewed HTTP requests")
    return ControlledHTTPPreview(
        preview_id="http-preview:" + uuid4().hex,
        assessment_id=scope.assessment_id,
        scope_sha256=_scope_hash(scope),
        runner_manifest_sha256=manifest,
        synthetic_object_id=item.object_id,
        spec=spec,
        control_spec=control_spec,
        actions=actions,
        created_at=now,
        expires_at=scope.expires_at,
        max_requests=request_cap,
        max_seconds=scope.budget.max_seconds,
        max_total_bytes=request_cap * MAX_RESPONSE,
    )


def validate_permission(
    scope: AssessmentScope,
    preview: ControlledHTTPPreview,
    permission: ControlledHTTPPermission,
    *,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    preview = ControlledHTTPPreview.model_validate(preview.model_dump())
    permission = ControlledHTTPPermission.model_validate(permission.model_dump())
    _validate_scope(scope, now)
    lab.admit(preview.spec)
    if preview.control_spec is not None:
        lab.admit(preview.control_spec)
        if preview.spec != lab.receipt_spec(
            preview.spec.marker
        ) or preview.control_spec != lab.receipt_spec(preview.spec.marker, invoice=True):
            raise ValueError("paired preview differs from the reviewed receipt/invoice pair")
    if (
        preview.scope_sha256 != _scope_hash(scope)
        or preview.assessment_id != scope.assessment_id
        or preview.actions != _actions(preview.spec, preview.control_spec)
        or preview.max_requests != sum(action.max_attempts for action in preview.actions)
        or preview.max_requests > scope.budget.max_requests
        or preview.max_seconds != scope.budget.max_seconds
        or preview.max_response_bytes != MAX_RESPONSE
        or preview.max_total_bytes != preview.max_requests * MAX_RESPONSE
        or preview.expires_at != scope.expires_at
        or preview.created_at > now
    ):
        raise ValueError("preview differs from the exact current scope or reviewed actions")
    item = next(
        (item for item in scope.synthetic_objects if item.object_id == preview.synthetic_object_id),
        None,
    )
    if (
        item is None
        or item.owner_account_id != "alice"
        or item.synthetic_marker != preview.spec.marker
    ):
        raise ValueError("preview synthetic object differs from the declaration")
    if (
        permission.preview_sha256 != preview.sha256
        or len(permission.approved_action_ids) != len(set(permission.approved_action_ids))
        or set(permission.approved_action_ids) != {action.action_id for action in preview.actions}
        or permission.granted_at < preview.created_at
        or permission.granted_at > now
        or permission.expires_at > preview.expires_at
        or permission.expires_at <= now
    ):
        raise ValueError("each exact previewed action requires current reviewed permission")


def _request(
    client: httpx.Client,
    origin: str,
    path: str,
    method: str,
    body: JsonValue,
    headers: Mapping[str, str],
    *,
    remaining_seconds: float,
    cancel: Callable[[], bool],
    deadline: float,
    clock: Callable[[], float],
    byte_budget: CollectionBytes | None = None,
    check_live: Callable[[], None] = lambda: None,
) -> tuple[int, dict[str, str], bytes]:
    validate_runtime_origin(origin)
    if not re.fullmatch(
        r"/(?:health|auth/login|orders(?:/[1-9][0-9]*/(?:receipt|invoice))?)", path
    ):
        raise CollectionStopped("request path is outside the exact reviewed lab surface")
    if cancel() or remaining_seconds <= 0:
        raise CollectionStopped("canceled or time budget exhausted")
    if (path == "/auth/login" or path == "/orders") != (method == "POST"):
        raise CollectionStopped("request method differs from reviewed lab action")
    data = bytearray()
    # No account inherits an implicit Cookie or default Authorization header.
    # The trusted fixture uses explicit per-account bearer tokens only.
    client.cookies.clear()
    if client.auth is not None or any(
        name.lower() in {"authorization", "cookie"} for name in client.headers
    ):
        raise CollectionStopped("implicit account credentials are refused")
    check_live()
    with client.stream(
        method,
        origin + path,
        headers=headers,
        json=body,
        follow_redirects=False,
        timeout=min(5.0, remaining_seconds),
    ) as response:
        if 300 <= response.status_code < 400:
            raise CollectionStopped("redirect refused; no destination or subresource was fetched")
        header_bytes = sum(
            len(key.encode()) + len(value.encode()) for key, value in response.headers.items()
        )
        if len(response.headers) > 100 or header_bytes > MAX_RESPONSE:
            raise CollectionStopped("response header collection budget exhausted")
        if byte_budget is not None:
            byte_budget.charge(header_bytes)
        for chunk in response.iter_bytes(chunk_size=4096):
            check_live()
            if cancel():
                raise CollectionStopped("canceled")
            if clock() >= deadline:
                raise CollectionStopped("time budget exhausted")
            if byte_budget is not None:
                byte_budget.charge(len(chunk))
            if len(data) + len(chunk) > MAX_RESPONSE:
                raise CollectionStopped("response collection budget exhausted")
            data.extend(chunk)
        check_live()
        if cancel() or clock() >= deadline:
            raise CollectionStopped("canceled or time budget exhausted")
        return response.status_code, dict(response.headers), bytes(data)


def run_controlled_http(
    scope: AssessmentScope,
    preview: ControlledHTTPPreview,
    permission: ControlledHTTPPermission,
    *,
    settings: Settings | None = None,
    cancel: Callable[[], bool] = lambda: False,
    clock: Callable[[], float] = time.perf_counter,
    checkpoint: Callable[[ControlledHTTPResult], None] = lambda result: None,
) -> ControlledHTTPResult:
    """Caller consumes a stored preview once; permission comes from reviewed UI/CLI.

    Authentication material stays in memory and is omitted from all records.
    Records still require the normal human attachment review before importing.
    The exact runtime port is supplied only by the verified worker handshake.
    """
    validate_permission(scope, preview, permission)
    settings = settings or Settings()
    if Redactor.configured(settings).text(preview.spec.marker) != preview.spec.marker:
        raise ValueError("synthetic marker contains configured private material")
    files, manifest = lab.verified_files()
    if manifest != preview.runner_manifest_sha256:
        raise ValueError("bundled manifest changed after action preview")
    started = clock()
    deadline = started + preview.max_seconds
    requests = 0
    records: list[dict[str, JsonValue]] = []
    origin = None
    stop = None
    tokens: list[str] = []
    headers: dict[str, dict[str, str]] = {}
    byte_budget = CollectionBytes(preview.max_total_bytes)
    progress = [HTTPActionProgress(action_id=action.action_id) for action in preview.actions]

    def snapshot(*, stopped: bool = False, reason: str | None = None) -> ControlledHTTPResult:
        rows = [
            row.model_copy(
                update={
                    "missing_evidence": []
                    if row.completed
                    else [
                        "Action attempted but completion/evidence is missing; do not replay"
                        if row.attempts
                        else "Approved action not attempted"
                    ]
                }
            )
            for row in progress
        ]
        return ControlledHTTPResult(
            preview_id=preview.preview_id,
            preview_sha256=preview.sha256,
            runner_manifest_sha256=manifest,
            runner_origin=origin,
            records=list(records),
            requests_used=requests,
            bytes_received=byte_budget.received,
            action_progress=rows,
            seconds=max(0.0, clock() - started),
            stopped=stopped,
            stop_reason=reason,
        )

    def attempted(action_index: int) -> None:
        nonlocal requests
        row = progress[action_index]
        if row.completed or row.attempts >= preview.actions[action_index].max_attempts:
            raise CollectionStopped("approved action attempts exhausted")
        requests += 1
        progress[action_index] = row.model_copy(update={"attempts": row.attempts + 1})
        # Durable callback runs before any HTTP byte; uncertain state changes are
        # never inferred absent on restart.
        checkpoint(snapshot())

    def completed(action_index: int, artifact_id: str | None = None) -> None:
        progress[action_index] = progress[action_index].model_copy(
            update={"completed": True, "artifact_ids": [artifact_id] if artifact_id else []}
        )
        checkpoint(snapshot())

    def check_live() -> None:
        if cancel():
            raise CollectionStopped("canceled")
        if datetime.now(UTC) >= min(scope.expires_at, permission.expires_at):
            raise CollectionStopped("scope or permission expired")
        if clock() >= deadline:
            raise CollectionStopped("time budget exhausted")

    def check() -> None:
        check_live()
        if requests >= preview.max_requests:
            raise CollectionStopped("request budget exhausted")
        if byte_budget.received >= byte_budget.maximum:
            raise CollectionStopped("aggregate response byte budget exhausted")

    def remaining_seconds() -> float:
        return min(
            deadline - clock(),
            (min(scope.expires_at, permission.expires_at) - datetime.now(UTC)).total_seconds(),
        )

    def ready(client: httpx.Client, runtime_origin: str) -> None:
        nonlocal requests, origin
        origin = runtime_origin
        validate_runtime_origin(runtime_origin)
        _scope_path(scope, "/health")
        for _ in range(preview.actions[0].max_attempts):
            check()
            attempted(0)
            try:
                status, response_headers, content = _request(
                    client,
                    runtime_origin,
                    "/health",
                    "GET",
                    None,
                    {},
                    remaining_seconds=min(0.2, remaining_seconds()),
                    cancel=cancel,
                    deadline=deadline,
                    clock=clock,
                    byte_budget=byte_budget,
                    check_live=check_live,
                )
            except httpx.HTTPError:
                time.sleep(min(0.1, max(0.0, deadline - clock())))
                continue
            redactor = Redactor.configured(settings, extra=("alice-lab-pass", "bob-lab-pass"))
            text = content.decode("utf-8", errors="strict")
            try:
                health = json.loads(text)
            except ValueError:
                health = None
            if (
                not isinstance(health, dict)
                or set(health) != {"status"}
                or not isinstance(health["status"], str)
                or health["status"] not in {"ok", "starting"}
            ):
                raise CollectionStopped("unexpected readiness metadata; collection stopped")
            if redactor.text(text) != text or any(
                redactor.text(value) != value for value in response_headers.values()
            ):
                raise CollectionStopped(
                    "unexpected sensitive readiness material; collection stopped"
                )
            if any(
                name.lower() in {"authorization", "set-cookie", "cookie"}
                for name in response_headers
            ):
                raise CollectionStopped(
                    "unexpected readiness cookie or credential header; collection stopped"
                )
            _collected_headers(response_headers, redactor)
            _collected_body(text, redactor, preview.spec.marker)
            client.cookies.clear()
            if status == 200:
                completed(0)
                return
        raise CollectionStopped("reviewed readiness attempts exhausted")

    try:
        check()
        with lab.launch(
            files,
            settings,
            readiness_hook=ready,
            startup_check=check,
            transport_factory=PinnedLoopbackTransport,
        ) as (
            origin,
            client,
        ):
            validate_runtime_origin(origin)
            for action_index, account in enumerate(("alice", "bob"), start=1):
                check()
                attempted(action_index)
                status, auth_response_headers, content = _request(
                    client,
                    origin,
                    "/auth/login",
                    "POST",
                    {"username": account, "password": account + "-lab-pass"},
                    {},
                    remaining_seconds=remaining_seconds(),
                    cancel=cancel,
                    deadline=deadline,
                    clock=clock,
                    byte_budget=byte_budget,
                    check_live=check_live,
                )
                # The expected fixture token is private operational state, not evidence.
                parsed = json.loads(content)
                token = parsed.get("token") if isinstance(parsed, dict) else None
                if status != 200 or not isinstance(token, str) or not token:
                    raise CollectionStopped("synthetic fixture authentication failed")
                if set(parsed) - {"token", "role"} or parsed.get("role", "customer") != "customer":
                    raise CollectionStopped(
                        "unexpected authentication metadata; collection stopped"
                    )
                redactor = Redactor.configured(
                    settings, extra=(*tokens, token, "alice-lab-pass", "bob-lab-pass")
                )
                if any(redactor.text(value) != value for value in auth_response_headers.values()):
                    raise CollectionStopped(
                        "unexpected sensitive authentication material; "
                        "stopped for private incident review"
                    )
                if any(
                    name.lower() in {"authorization", "set-cookie", "cookie"}
                    for name in auth_response_headers
                ):
                    raise CollectionStopped(
                        "unexpected sensitive authentication header; collection stopped"
                    )
                _collected_headers(auth_response_headers, redactor)
                tokens.append(token)
                headers[account] = {"authorization": "Bearer " + token}
                client.cookies.clear()
                completed(action_index)
            variables = {"marker": preview.spec.marker}
            session = "session:" + uuid4().hex
            probe_requests = [
                *preview.spec.requests,
                *(preview.control_spec.requests[1:] if preview.control_spec else []),
                *([preview.control_spec.requests[1]] if preview.control_spec else []),
            ]
            for index, request in enumerate(probe_requests):
                check()
                path = substitute(request.path, variables, path=True)
                _scope_path(scope, path)
                payload = body_value(request.body, variables)
                attempted(index + 3)
                status, response_headers, content = _request(
                    client,
                    origin,
                    path,
                    request.method,
                    payload,
                    headers[request.principal],
                    remaining_seconds=remaining_seconds(),
                    cancel=cancel,
                    deadline=deadline,
                    clock=clock,
                    byte_budget=byte_budget,
                    check_live=check_live,
                )
                redactor = Redactor.configured(
                    settings, extra=(*tokens, "alice-lab-pass", "bob-lab-pass")
                )
                text = content.decode("utf-8", errors="strict")
                if redactor.text(text) != text or any(
                    redactor.text(value) != value for value in response_headers.values()
                ):
                    raise CollectionStopped(
                        "unexpected sensitive material; stopped for private incident review"
                    )
                if any(
                    name.lower() in {"authorization", "set-cookie", "cookie"}
                    for name in response_headers
                ):
                    raise CollectionStopped(
                        "unexpected sensitive response header; collection stopped"
                    )
                _collected_headers(response_headers, redactor)
                client.cookies.clear()
                text = _collected_body(text, redactor, preview.spec.marker)
                if index == 0:
                    if not 200 <= status < 300:
                        raise CollectionStopped("synthetic setup failed")
                    parsed = json.loads(content)
                    order_id = parsed.get("id") if isinstance(parsed, dict) else None
                    if type(order_id) is not int or not 0 < order_id < 2**53:
                        raise CollectionStopped(
                            "synthetic setup did not return a valid object identifier"
                        )
                    variables["order_id"] = str(order_id)
                records.append(
                    {
                        "artifact_id": f"http:{preview.preview_id.split(':')[-1]}:{index}",
                        "collected_at": datetime.now(UTC).isoformat(),
                        "provenance": "Reviewed hash-pinned owned Tandir HTTP collection; manifest "
                        + manifest,
                        "context": {
                            "account_id": request.principal,
                            "object_id": preview.synthetic_object_id,
                            "session_context_id": session + ":" + request.principal,
                            "request_context_id": "request:"
                            + hashlib.sha256(
                                ("synthetic-order:" + variables.get("order_id", "setup")).encode()
                            ).hexdigest()[:24],
                        },
                        "request": {"method": request.method, "url": origin + path, "headers": {}},
                        "response": {
                            "status": status,
                            "headers": {
                                name: value
                                for name, value in response_headers.items()
                                if name.lower() == "content-type"
                            },
                            "body": text,
                        },
                    }
                )
                completed(index + 3, str(records[-1]["artifact_id"]))
            if cancel():
                raise CollectionStopped("canceled")
            if clock() >= deadline:
                raise CollectionStopped("time budget exhausted")
    except (
        CollectionStopped,
        httpx.HTTPError,
        ValueError,
        UnicodeError,
        lab.LabUnavailable,
    ) as error:
        stop = str(error) if isinstance(error, CollectionStopped) else type(error).__name__
    finally:
        headers.clear()
        tokens.clear()
    result = snapshot(stopped=stop is not None, reason=stop)
    checkpoint(result)
    return result

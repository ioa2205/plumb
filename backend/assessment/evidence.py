"""Inert, bounded imports and exact-field citations for privately reviewed observations."""

import base64
import binascii
import hashlib
import json
import re
import struct
import zlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.contracts.assessment import (
    AssessmentScope,
    AssessmentView,
    AttachmentReview,
    EvidenceArtifact,
    EvidenceCitation,
    ObservationContext,
    normalized_path,
)
from backend.redaction import TOKEN, Redactor

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 1024 * 1024
_PRIVATE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|cookie|session|api[-_]?key|"
    r"email|phone|address|birth|credit|card|payment|ssn|iban)"
)
_CREDENTIAL_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|cookie|session|api[-_]?key)"
)
_PERSONAL_KEY = re.compile(r"(?i)(email|phone|address|birth|credit|card|payment|ssn|iban)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_HEADER = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}$")
_ASSIGNMENT = re.compile(
    r"(?i)((?:password|passwd|secret|token|cookie|session|api[-_]?key)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s&;,<>]+)"
)


class SensitiveDiscovery(ValueError):
    """The import disclosed unexpected personal information; originals are discarded."""


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _text(value: object, name: str, limit: int = 65536) -> str:
    if not isinstance(value, str) or len(value.encode()) > limit:
        raise ValueError(f"{name} must be bounded text")
    return value


def _time(value: object, name: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, name, 100).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO timestamp") from error
    if result.tzinfo is None:
        raise ValueError(f"{name} requires a timezone")
    return result


def check_scope(
    scope: AssessmentScope,
    *,
    action: str | None = None,
    url: str | None = None,
    now: datetime | None = None,
) -> None:
    """No prompt, HTTP method or imported artifact creates testing authority."""
    scope = AssessmentScope.model_validate(scope.model_dump())
    now = now or datetime.now(UTC)
    if now >= scope.expires_at or now < scope.authority.granted_at:
        raise ValueError("assessment scope is expired or not yet active")
    if action is not None and action not in scope.allowed_actions:
        raise ValueError("action is outside the explicit assessment scope")
    if url is not None:
        parsed = urlsplit(url)
        expected = urlsplit(scope.origin)
        if (
            parsed.scheme != expected.scheme
            or parsed.hostname != expected.hostname
            or parsed.port != expected.port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or any(ord(char) < 32 for char in url)
        ):
            raise ValueError("observation URL is outside the explicit application origin")
        path = normalized_path(parsed.path or "/")
        if not any(
            path == root or path.startswith(root.rstrip("/") + "/") for root in scope.allowed_paths
        ):
            raise ValueError("observation path is outside the explicit scope")


def _safe_text(value: str, redactor: Redactor, *, personal_stop: bool = False) -> str:
    if personal_stop and _EMAIL.search(value):
        raise SensitiveDiscovery("Unexpected personal information: collection is stopped.")
    sanitized = _EMAIL.sub(TOKEN, redactor.text(value))
    return _ASSIGNMENT.sub(lambda match: match[1] + TOKEN, sanitized)


def _sanitize_tree(
    value: object,
    redactor: Redactor,
    depth: int = 0,
    allowed_synthetic_values: tuple[str, ...] = (),
) -> object:
    if depth > 12:
        raise ValueError("body nesting exceeds the inert parser budget")
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValueError("body object exceeds the field budget")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or redactor.text(key) != key:
                raise ValueError("body keys must be credential-free text")
            if (
                _PERSONAL_KEY.search(key)
                and item not in (None, "", TOKEN)
                and item not in allowed_synthetic_values
            ):
                raise SensitiveDiscovery("Unexpected personal information: collection is stopped.")
            result[key] = (
                item
                if _PERSONAL_KEY.search(key)
                and isinstance(item, str)
                and item in allowed_synthetic_values
                else TOKEN
                if _PRIVATE_KEY.search(key)
                else _sanitize_tree(item, redactor, depth + 1, allowed_synthetic_values)
            )
        return result
    if isinstance(value, list):
        if len(value) > 200:
            raise ValueError("body list exceeds the item budget")
        return [
            _sanitize_tree(item, redactor, depth + 1, allowed_synthetic_values) for item in value
        ]
    if isinstance(value, str):
        return _safe_text(value, redactor, personal_stop=True)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    raise ValueError("body contains an unsupported JSON value")


def _body(value: object, redactor: Redactor, allowed_synthetic_values: tuple[str, ...] = ()) -> str:
    text = _text(value, "body")
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        if "=" in text and not any(char in text for char in "<>\n"):
            pairs = parse_qsl(text, keep_blank_values=True, max_num_fields=200)
            if pairs:
                if any(_PERSONAL_KEY.search(key) and item for key, item in pairs):
                    raise SensitiveDiscovery(
                        "Unexpected personal information: collection is stopped."
                    ) from None
                return urlencode(
                    [
                        (key, TOKEN if _PRIVATE_KEY.search(key) else _safe_text(item, redactor))
                        for key, item in pairs
                    ]
                )
        # Preserve hostile HTML only as text; never render or fetch it.
        return _safe_text(text, redactor, personal_stop=True)
    return _json(
        _sanitize_tree(parsed, redactor, allowed_synthetic_values=allowed_synthetic_values)
    )


def _metadata_value(
    key: str,
    value: str,
    redactor: Redactor,
    allowed_synthetic_values: tuple[str, ...],
) -> str:
    # Operational credentials are discarded, even if they equal a declared marker.
    if _CREDENTIAL_KEY.search(key):
        return TOKEN
    if _PERSONAL_KEY.search(key):
        if value not in ("", TOKEN) and value not in allowed_synthetic_values:
            raise SensitiveDiscovery("Unexpected personal information: collection is stopped.")
        return redactor.text(value)
    return _safe_text(value, redactor, personal_stop=True)


def _headers(
    value: object, redactor: Redactor, allowed_synthetic_values: tuple[str, ...] = ()
) -> dict[str, str]:
    headers = _mapping(value, "headers")
    if len(headers) > 100:
        raise ValueError("header count exceeds the import budget")
    result: dict[str, str] = {}
    for key, item in headers.items():
        if not _HEADER.fullmatch(key) or key.lower() in result:
            raise ValueError("header names must be unique inert names")
        lower = key.lower()
        text = _text(item, "header", 8192)
        result[lower] = _metadata_value(lower, text, redactor, allowed_synthetic_values)
    return result


def _safe_url(
    value: object,
    scope: AssessmentScope,
    redactor: Redactor,
    *,
    now: datetime | None = None,
) -> str:
    url = _text(value, "request URL", 2048)
    check_scope(scope, url=url, now=now)
    parsed = urlsplit(url)
    markers = tuple(obj.synthetic_marker for obj in scope.synthetic_objects if obj.synthetic_marker)
    # Use the scope's existing bounded decoder to recognize hidden personal data.
    # Preserve safe observed path spelling rather than inventing another request URL.
    for segment in normalized_path(parsed.path or "/").split("/"):
        sanitized = (
            redactor.text(segment)
            if segment in markers
            else _safe_text(segment, redactor, personal_stop=True)
        )
        if sanitized != segment:
            raise ValueError("request path must be sanitized before import")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)
    query = urlencode(
        [
            (
                _safe_text(key, redactor, personal_stop=True),
                _metadata_value(key, item, redactor, markers),
            )
            for key, item in pairs
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))


def validate_observation_metadata(
    scope: AssessmentScope, fields: dict[str, str], redactor: Redactor
) -> None:
    """Recheck saved metadata before context/export, including rehashed tampering."""
    if (
        _safe_url(fields["request.url"], scope, redactor, now=scope.authority.granted_at)
        != fields["request.url"]
    ):
        raise ValueError("saved observation URL is not sanitized inert data")
    markers = tuple(obj.synthetic_marker for obj in scope.synthetic_objects if obj.synthetic_marker)
    for prefix in ("request.headers.", "response.headers."):
        headers = {
            key.removeprefix(prefix): value
            for key, value in fields.items()
            if key.startswith(prefix)
        }
        if _headers(headers, redactor, markers) != headers:
            raise ValueError("saved observation headers are not sanitized inert data")


def artifact_digest(artifact: EvidenceArtifact) -> str:
    return digest(
        _json(
            {
                "kind": artifact.kind,
                "fields": artifact.fields,
                "context": artifact.context.model_dump() if artifact.context else None,
                "collected_at": artifact.collected_at.isoformat(),
                "provenance": artifact.provenance,
            }
        )
    )


def _artifact(
    scope: AssessmentScope,
    record: dict[str, Any],
    review: AttachmentReview,
    fields: dict[str, str],
    kind: str,
    redactor: Redactor,
    context: ObservationContext | None = None,
) -> EvidenceArtifact:
    now = datetime.now(UTC)
    if review.reviewed_at > now:
        raise ValueError("human review cannot be in the future")
    provenance = _safe_text(_text(record.get("provenance"), "provenance", 4096), redactor)
    collected_at = _time(record.get("collected_at"), "collection time")
    if collected_at > now or collected_at > review.reviewed_at:
        raise ValueError("collection must precede human review and import")
    identity = record.get("artifact_id", "E-" + digest(_json(fields))[:16])
    artifact = EvidenceArtifact.model_validate(
        {
            "artifact_id": identity,
            "assessment_id": scope.assessment_id,
            "kind": kind,
            "sha256": "0" * 64,
            "collected_at": collected_at,
            "imported_at": now,
            "provenance": provenance,
            "review": review,
            "fields": fields,
            "context": context,
        }
    )
    return EvidenceArtifact.model_validate(
        {**artifact.model_dump(), "sha256": artifact_digest(artifact)}
    )


def sanitize_http_record(
    scope: AssessmentScope,
    record: object,
    review: AttachmentReview,
    redactor: Redactor | None = None,
) -> EvidenceArtifact:
    """Accept one human-reviewed inert record; no transport or target code is called."""
    check_scope(scope, action="read")
    review = AttachmentReview.model_validate(review.model_dump())
    redactor = redactor or Redactor()
    data = _mapping(record, "record")
    if data.get("unexpected_sensitive_information"):
        raise SensitiveDiscovery("Unexpected sensitive information: collection is stopped.")
    context = ObservationContext.model_validate(data.get("context"))
    if context.account_id not in {account.account_id for account in scope.accounts}:
        raise ValueError("record account is not a designated test account")
    if context.object_id not in {item.object_id for item in scope.synthetic_objects}:
        raise ValueError("record object is not a designated synthetic object")
    request = _mapping(data.get("request"), "request")
    response = _mapping(data.get("response"), "response")
    method = _text(request.get("method"), "method", 20).upper()
    if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported observation method")
    status = response.get("status")
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise ValueError("response status must be an observed HTTP status")
    fields = {
        "request.method": method,
        "request.url": _safe_url(request.get("url"), scope, redactor),
        "response.status": str(status),
        "request.body": _body(
            request.get("body", ""),
            redactor,
            tuple(
                item.synthetic_marker for item in scope.synthetic_objects if item.synthetic_marker
            ),
        ),
        "response.body": _body(
            response.get("body", ""),
            redactor,
            tuple(
                item.synthetic_marker for item in scope.synthetic_objects if item.synthetic_marker
            ),
        ),
    }
    for prefix, section in (("request", request), ("response", response)):
        for key, value in _headers(
            section.get("headers", {}),
            redactor,
            tuple(obj.synthetic_marker for obj in scope.synthetic_objects if obj.synthetic_marker),
        ).items():
            fields[f"{prefix}.headers.{key}"] = value
    return _artifact(scope, data, review, fields, "request_response", redactor, context)


def _png(value: object) -> bytes:
    try:
        data = base64.b64decode(_text(value, "screenshot base64", 1500000), validate=True)
    except binascii.Error as error:
        raise ValueError("screenshot must be bounded base64 PNG data") from error
    if len(data) > MAX_ATTACHMENT_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("only bounded reviewed PNG screenshots are supported")
    cursor = 8
    chunks = [data[:8]]
    types: list[bytes] = []
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise ValueError("malformed screenshot PNG")
        size = struct.unpack(">I", data[cursor : cursor + 4])[0]
        end = cursor + 12 + size
        if end > len(data):
            raise ValueError("malformed screenshot PNG chunk")
        kind = data[cursor + 4 : cursor + 8]
        body = data[cursor + 8 : end - 4]
        crc = struct.unpack(">I", data[end - 4 : end])[0]
        if zlib.crc32(kind + body) != crc:
            raise ValueError("screenshot PNG checksum is invalid")
        if kind == b"IHDR":
            if types or size != 13:
                raise ValueError("screenshot PNG header is invalid")
            width, height = struct.unpack(">II", body[:8])
            if not width or not height or width > 4096 or height > 4096 or width * height > 8000000:
                raise ValueError("screenshot exceeds the pixel budget")
        if kind in {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}:
            chunks.append(data[cursor:end])
        elif kind[0] & 32 == 0:
            raise ValueError("unsupported screenshot PNG critical chunk")
        types.append(kind)
        cursor = end
        if kind == b"IEND":
            if size or cursor != len(data):
                raise ValueError("screenshot PNG has trailing content")
            break
    if not types or types[0] != b"IHDR" or types[-1] != b"IEND" or b"IDAT" not in types:
        raise ValueError("screenshot PNG is incomplete")
    return b"".join(chunks)


def parse_import(
    scope: AssessmentScope,
    payload: str | bytes,
    review: AttachmentReview,
    redactor: Redactor,
) -> tuple[list[EvidenceArtifact], dict[str, bytes]]:
    """Selected HAR entries, records, notes and reviewed screenshots, with no side effects."""
    raw = payload.encode() if isinstance(payload, str) else payload
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("import exceeds the 2 MiB budget")
    check_scope(scope, action="read")
    review = AttachmentReview.model_validate(review.model_dump())
    try:
        root = _mapping(json.loads(raw), "import")
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("import must be bounded JSON") from error
    if "har" in root:
        har = _mapping(root["har"], "HAR")
        entries = _mapping(har.get("log"), "HAR log").get("entries")
        selected = root.get("selected_entries")
        contexts = _mapping(root.get("contexts"), "HAR contexts")
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError("HAR entry count exceeds the import budget")
        if not isinstance(selected, list) or not selected or len(selected) > 100:
            raise ValueError("HAR import requires explicitly selected entry indexes")
        records: list[object] = []
        for index in selected:
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(entries)
            ):
                raise ValueError("selected HAR entry index is invalid")
            entry = _mapping(entries[index], "HAR entry")
            request = _mapping(entry.get("request"), "HAR request")
            response = _mapping(entry.get("response"), "HAR response")

            def headers(section: dict[str, Any]) -> dict[str, str]:
                result: dict[str, str] = {}
                pairs = section.get("headers", [])
                if not isinstance(pairs, list) or len(pairs) > 100:
                    raise ValueError("HAR headers exceed the import budget")
                for pair in pairs:
                    part = _mapping(pair, "HAR header")
                    key = _text(part.get("name"), "HAR header name", 100)
                    if key.lower() in {name.lower() for name in result}:
                        raise ValueError("duplicate HAR header")
                    result[key] = _text(part.get("value"), "HAR header value", 8192)
                return result

            content = _mapping(response.get("content", {}), "HAR content")
            if content.get("encoding") not in {None, ""}:
                raise ValueError("encoded HAR response bodies require a reviewed plain-text record")
            post = _mapping(request.get("postData", {}), "HAR request data")
            records.append(
                {
                    "artifact_id": f"E-har-{index}-{digest(_json(entry))[:12]}",
                    "collected_at": entry.get("startedDateTime"),
                    "provenance": root.get("provenance"),
                    "context": contexts.get(str(index)),
                    "request": {
                        "method": request.get("method"),
                        "url": request.get("url"),
                        "headers": headers(request),
                        "body": post.get("text", ""),
                    },
                    "response": {
                        "status": response.get("status"),
                        "headers": headers(response),
                        "body": content.get("text", ""),
                    },
                }
            )
    else:
        records = root.get("records", [])
        if not isinstance(records, list) or not records or len(records) > 100:
            raise ValueError("import requires between 1 and 100 records")
    artifacts: list[EvidenceArtifact] = []
    attachments: dict[str, bytes] = {}
    for item in records:
        record = _mapping(item, "record")
        kind = record.get("kind", "request_response")
        if kind == "request_response":
            artifact = sanitize_http_record(scope, record, review, redactor)
        elif kind == "note":
            artifact = _artifact(
                scope,
                record,
                review,
                {
                    "note.text": _safe_text(
                        _text(record.get("text"), "note"), redactor, personal_stop=True
                    )
                },
                "note",
                redactor,
            )
        elif kind == "screenshot":
            image = _png(record.get("content_base64"))
            artifact = _artifact(
                scope,
                record,
                review,
                {
                    "screenshot.sha256": digest(image),
                    "screenshot.description": _safe_text(
                        _text(record.get("description"), "screenshot description", 4096),
                        redactor,
                        personal_stop=True,
                    ),
                    "screenshot.interpretation": (
                        "Human-reviewed attachment; image understanding unavailable."
                    ),
                },
                "screenshot",
                redactor,
            )
            attachments[artifact.artifact_id] = image
        else:
            raise ValueError("unsupported inert import kind")
        artifacts.append(artifact)
    if len({artifact.artifact_id for artifact in artifacts}) != len(artifacts):
        raise ValueError("import contains duplicate artifact IDs")
    return artifacts, attachments


def artifact_citation(artifact: EvidenceArtifact, field: str) -> EvidenceCitation:
    if field not in artifact.fields:
        raise ValueError("citation field does not exist")
    return EvidenceCitation(
        artifact_id=artifact.artifact_id, field=field, sha256=digest(artifact.fields[field])
    )


def resolve_citation(view: AssessmentView, citation: EvidenceCitation) -> str:
    citation = EvidenceCitation.model_validate(citation.model_dump())
    matches = [item for item in view.artifacts if item.artifact_id == citation.artifact_id]
    if len(matches) != 1:
        raise ValueError("citation artifact does not uniquely resolve")
    artifact = matches[0]
    if artifact.sha256 != artifact_digest(artifact):
        raise ValueError("artifact hash no longer resolves")
    if (
        citation.field not in artifact.fields
        or digest(artifact.fields[citation.field]) != citation.sha256
    ):
        raise ValueError("citation field/hash does not resolve")
    return artifact.fields[citation.field]


sanitize_observation_body = _body
sanitize_observation_headers = _headers

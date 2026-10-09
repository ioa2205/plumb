"""Shared redaction before model, log and export serialization (PROJECT_PLAN §8).

Known credential shapes plus caller-supplied literal values. This is not a
general detector for arbitrary secrets; source text is not included in reports.
"""

import hashlib
import json
import logging
import re
import traceback
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import IO, Any

from backend.settings import Settings

TOKEN = "[REDACTED]"  # noqa: S105 - replacement text
_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?"
        r"(?:-----END (?:[A-Z ]+ )?PRIVATE KEY-----|\Z)",
        re.S,
    ),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_ASSIGNMENT = re.compile(
    r"(?i)((?<!\w)[\"']?(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret|"
    r"authorization)\b[\"']?\s*[:=]\s*)(?:Bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_URL_AUTH = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@")


@dataclass(frozen=True)
class CredentialShape:
    rule: str
    start: int
    end: int
    fingerprint: str


def credential_shapes(text: str, namespace: str) -> list[CredentialShape]:
    """Pattern observations without carrying matched values across the boundary."""
    results = []
    patterns = [
        *zip(
            ("private-key", "github-token", "aws-key-id", "api-token", "jwt"),
            _PATTERNS,
            strict=True,
        ),
        ("credential-assignment", _ASSIGNMENT),
        ("url-credentials", _URL_AUTH),
    ]
    for rule, pattern in patterns:
        for match in pattern.finditer(text):
            if TOKEN in match[0]:
                continue
            digest = hashlib.sha256((namespace + "\0" + match[0]).encode()).hexdigest()
            results.append(CredentialShape(rule, match.start(), match.end(), digest))
            if len(results) > 100:
                return results
    return results


def redact(text: str, secrets: Sequence[str] = (), *, preserve_lines: bool = False) -> str:
    """Redact without logging or retaining the original value."""

    def replacement(value: str) -> str:
        return TOKEN + ("\n" + TOKEN) * value.count("\n") if preserve_lines else TOKEN

    for value in sorted(set(secrets), key=len, reverse=True):
        if not value:
            raise ValueError("a redaction value cannot be empty")
        text = text.replace(value, replacement(value))
    for pattern in _PATTERNS:
        text = pattern.sub(lambda match: replacement(match[0]), text)
    text = _URL_AUTH.sub(r"\1[REDACTED]@", text)
    return _ASSIGNMENT.sub(lambda match: match[1] + replacement(match[0][len(match[1]) :]), text)


@dataclass(frozen=True)
class Redactor:
    """A process-bound policy; originals stay in memory, never in its repr."""

    secrets: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if any(not value for value in self.secrets):
            raise ValueError("a redaction value cannot be empty")

    @classmethod
    def configured(
        cls, settings: Settings | None = None, *, extra: Sequence[str] = ()
    ) -> "Redactor":
        settings = settings or Settings()
        return cls(
            tuple(value.get_secret_value() for value in settings.redaction_secrets) + tuple(extra)
        )

    def text(self, value: str, *, preserve_lines: bool = False) -> str:
        # Context escapes, JSON diagnostics and developer-note whitespace folding must
        # not hide configured values from the same policy.
        variants = set(self.secrets)
        for secret in self.secrets:
            variants.update(
                (
                    json.dumps(secret)[1:-1],
                    json.dumps(secret, ensure_ascii=False)[1:-1],
                    repr(secret)[1:-1],
                    " ".join(secret.split()),
                    "".join(
                        ch
                        if ch == "\t"
                        or unicodedata.category(ch) not in {"Cc", "Cf", "Zl", "Zp", "Co", "Cs"}
                        else f"\\u{{{ord(ch):x}}}"
                        for ch in secret
                    ),
                )
            )
        return redact(
            value, tuple(part for part in variants if part), preserve_lines=preserve_lines
        )

    def strings(self, value: Any) -> Any:  # noqa: ANN401 - a JSON tree at a serialization boundary
        """Copy a JSON tree; callers can refuse changed identities or schema enums."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.strings(item) for item in value]
        if isinstance(value, dict):
            if any(self.text(key) != key for key in value):
                raise ValueError("a credential occurs in a JSON key")
            return {key: self.strings(item) for key, item in value.items()}
        return value

    def exception(self, logger: logging.Logger, message: str, error: BaseException) -> None:
        # Give every handler a sanitized record, including the exception chain and
        # source lines. exc_info would let a different formatter serialize originals.
        detail = "".join(traceback.format_exception(error))
        logger.error("%s", self.text(f"{message}\n{detail}"))


LOG_LIMIT = 1024 * 1024


def capture_log(
    source: IO[bytes], output: IO[str], redactor: Redactor, *, limit: int = LOG_LIMIT
) -> None:
    """Drain a child pipe, then serialize one sanitized record at EOF.

    At most 1 MiB is kept in memory. On overflow, discard the whole record so
    neither a partial configured value nor an unfinished key can leak. Draining
    continues so the child cannot deadlock on a full pipe. No raw spool file.
    """
    captured = bytearray()
    overflow = False
    while chunk := source.read(8192):
        if not overflow:
            if len(captured) + len(chunk) > limit:
                captured.clear()
                overflow = True
            else:
                captured.extend(chunk)
    text = (
        "[model log omitted: size limit exceeded]\n"
        if overflow
        else redactor.text(captured.decode("utf-8", errors="replace"))
    )
    captured.clear()
    output.write(text)
    output.flush()

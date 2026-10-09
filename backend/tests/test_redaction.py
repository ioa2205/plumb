import pytest

from backend.redaction import TOKEN, redact


@pytest.mark.parametrize(
    "value",
    [
        "ghp_" + "a" * 36,
        "github_pat_" + "b" * 30,
        "AKIA" + "A" * 16,
        "sk-" + "q" * 30,
        "eyJheader.payload.signature",
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
    ],
)
def test_known_shapes_are_redacted(value: str) -> None:
    assert redact(f"Before {value} after") == f"Before {TOKEN} after"


@pytest.mark.parametrize(
    "text",
    [
        'password="fixture password"',
        "api_key: abc",
        "Authorization: Bearer abc",
        "client_secret='fixture'",
        "access_token=fixture",
        '"password": "fixture password"',
        "'api_key': 'fixture'",
    ],
)
def test_credential_assignments_are_redacted(text: str) -> None:
    assert redact(text).endswith(TOKEN)
    assert "fixture" not in redact(text)


def test_url_credentials_and_literal_values_are_redacted() -> None:
    assert redact("https://alice:fixture@localhost/path") == "https://[REDACTED]@localhost/path"
    assert redact("long-value short", ["long-value", "short"]) == "[REDACTED] [REDACTED]"
    with pytest.raises(ValueError):
        redact("unchanged", [""])


def test_ordinary_evidence_ids_and_hashes_are_not_redacted() -> None:
    text = "F-07/E01 finding:1 " + "a" * 64
    assert redact(text) == text

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from backend.app import create_app
from backend.security import CONTENT_SECURITY_POLICY, content_security_policy
from backend.settings import Settings
from backend.workbench import MANIFEST_NAME, UNAVAILABLE, _Scripts

from .support import ORIGIN, PORT, signed_in, visitor

SCRIPT = "\n console.log('typography: \u2160 ≠ 1');\n"
HTML = (
    f"<!doctype html><html><body><h1>Foundation</h1><script>{SCRIPT}</script></body></html>"
).encode()


def script_hash(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


def write_export(root: Path, files: dict[str, bytes]) -> None:
    entries = {}
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries[name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "script_hashes": list(_Scripts().finish(content)) if name.endswith(".html") else [],
        }
    (root / MANIFEST_NAME).write_text(json.dumps({"version": 1, "files": entries}))


@pytest.fixture
def exported(tmp_path: Path) -> tuple[FastAPI, Path]:
    root = tmp_path / "export"
    write_export(
        root,
        {
            "foundation/index.html": HTML,
            "other/index.html": b"<html><body><script>console.log('other')</script></body></html>",
            "_next/static/app.js": b"console.log('own bundle');",
            "_next/static/app.css": b"body { margin: 0; }",
            "fonts/license.txt": b"Font license",
        },
    )
    return create_app(Settings(data_dir=tmp_path / "data"), port=PORT, workbench_dir=root), root


def test_inline_hash_is_exact_utf8_content_with_browser_newline_normalization() -> None:
    assert _Scripts().finish(HTML) == (script_hash(SCRIPT),)
    windows = HTML.replace(b"\n", b"\r\n")
    assert _Scripts().finish(windows) == (script_hash(SCRIPT),)
    assert _Scripts().finish(HTML.replace(b" console", b"console")) != (script_hash(SCRIPT),)


@pytest.mark.parametrize(
    "bad", ["'unsafe-inline'", "sha256-x; connect-src *", "sha256-\r\nX-Test: x", ""]
)
def test_policy_rejects_anything_except_digest_sources(bad: str) -> None:
    with pytest.raises(ValueError, match="hashes"):
        content_security_policy((bad,))
    with pytest.raises(ValueError, match="hashes"):
        content_security_policy((script_hash(SCRIPT),) * 65)


def test_only_verified_document_scripts_extend_the_base_policy(
    exported: tuple[FastAPI, Path],
) -> None:
    app, _ = exported
    client = signed_in(app)
    page = client.get("/foundation/?run=ignored")
    assert page.status_code == 200 and page.content == HTML
    policy = page.headers["content-security-policy"]
    assert policy == content_security_policy((script_hash(SCRIPT),))
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert "script-src-attr 'none'" in policy and "style-src-attr 'none'" in policy
    other = client.get("/other/")
    assert script_hash(SCRIPT) not in other.headers["content-security-policy"]
    assert (
        client.get("/api/runs/missing").headers["content-security-policy"]
        == CONTENT_SECURITY_POLICY
    )


@pytest.mark.parametrize("path", ["/foundation/", "/_next/static/app.js", "/fonts/license.txt"])
def test_all_export_files_require_the_existing_session(
    exported: tuple[FastAPI, Path], path: str
) -> None:
    app, _ = exported
    response = visitor(app).get(path)
    assert response.status_code == 401
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Host": "foreign.example"}, 421),
        ({"Origin": "http://127.0.0.1:8702"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
    ],
)
def test_workbench_does_not_bypass_host_or_origin_checks(
    exported: tuple[FastAPI, Path], headers: dict[str, str], status: int
) -> None:
    app, _ = exported
    response = signed_in(app).get("/foundation/", headers=headers)
    assert response.status_code == status
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_assets_head_requests_and_unknown_paths_are_bounded(exported: tuple[FastAPI, Path]) -> None:
    app, root = exported
    client = signed_in(app)
    for path, mime in [
        ("/_next/static/app.js", "text/javascript"),
        ("/_next/static/app.css", "text/css"),
        ("/fonts/license.txt", "text/plain"),
    ]:
        response = client.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith(mime)
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert response.headers["cache-control"] == "no-store"
        assert client.head(path).content == b""
    assert client.head("/foundation/").headers["content-length"] == str(len(HTML))
    (root / "unlisted.txt").write_text("not in the export")
    for path in [
        "/unlisted.txt",
        "/plumb-export.json",
        "/api/unlisted.txt",
        "/.env",
        "/foundation/%2e%2e/%2e%2e/private.txt",
        "/foundation%5cindex.html",
        "/foundation/index.html:extra",
        "/404.html",
    ]:
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert client.post("/foundation/", headers={"Origin": ORIGIN}).status_code == 405
    assert (
        client.post("/api/runs/..%2Foutside/cancel", headers={"Origin": ORIGIN}).status_code == 404
    )


@pytest.mark.parametrize(
    "name", ["foundation/index.html", "_next/static/app.js", "_next/static/app.css"]
)
def test_modified_assets_refuse_before_serving_or_extending_csp(
    exported: tuple[FastAPI, Path], name: str
) -> None:
    app, root = exported
    path = root / name
    path.write_bytes(path.read_bytes() + b"changed")
    response = signed_in(app).get("/" + name)
    assert (response.status_code, response.text) == (503, UNAVAILABLE)
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "changed" not in response.text and str(root) not in response.text


@pytest.mark.parametrize(
    "markup",
    [
        b'<span style="color:red">x</span>',
        b"<style>body{}</style>",
        b'<button onclick="x()">x</button>',
        b'<script src="https://foreign.invalid/x.js"></script>',
        b"<script>unterminated",
    ],
)
def test_even_a_manifested_page_cannot_admit_inline_styles_events_or_foreign_scripts(
    tmp_path: Path, markup: bytes
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    (root / "index.html").write_bytes(markup)
    item = {"sha256": hashlib.sha256(markup).hexdigest(), "bytes": len(markup), "script_hashes": []}
    (root / MANIFEST_NAME).write_text(json.dumps({"version": 1, "files": {"index.html": item}}))
    app = create_app(Settings(data_dir=tmp_path / "data"), port=PORT, workbench_dir=root)
    response = signed_in(app).get("/")
    assert (response.status_code, response.text) == (503, UNAVAILABLE)


@pytest.mark.parametrize(
    "name",
    [
        "../outside.txt",
        "/outside.txt",
        "asset\\file.js",
        "asset:stream.js",
        "con.txt",
        "assets/nul.txt",
        "assets/space .txt",
        "assets/file.txt.",
        "assets/.env",
        "api/index.html",
        "plumb-export.json",
        "404/index.html",
        "_not-found/index.html",
    ],
)
def test_unsafe_manifest_names_make_only_the_workbench_unavailable(
    tmp_path: Path, name: str
) -> None:
    root = tmp_path / "export"
    root.mkdir()
    item = {"sha256": "0" * 64, "bytes": 1, "script_hashes": []}
    (root / MANIFEST_NAME).write_text(json.dumps({"version": 1, "files": {name: item}}))
    app = create_app(Settings(data_dir=tmp_path / "data"), port=PORT, workbench_dir=root)
    client = signed_in(app)
    assert (client.get("/").status_code, client.get("/").text) == (503, UNAVAILABLE)
    assert client.get("/api/runs/missing").status_code == 404


def test_manifest_script_mismatch_does_not_add_a_hash_to_the_response(
    exported: tuple[FastAPI, Path], tmp_path: Path
) -> None:
    _, root = exported
    manifest = json.loads((root / MANIFEST_NAME).read_text())
    manifest["files"]["foundation/index.html"]["script_hashes"] = [script_hash("different")]
    (root / MANIFEST_NAME).write_text(json.dumps(manifest))
    app = create_app(Settings(data_dir=tmp_path / "other"), port=PORT, workbench_dir=root)
    response = signed_in(app).get("/foundation/")
    assert response.status_code == 503
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_duplicate_and_case_colliding_manifest_entries_refuse(
    exported: tuple[FastAPI, Path], tmp_path: Path
) -> None:
    _, root = exported
    for raw in [
        '{"version":1,"version":1,"files":{}}',
        json.dumps(
            {
                "version": 1,
                "files": {
                    "a.js": {"sha256": "0" * 64, "bytes": 0, "script_hashes": []},
                    "A.js": {"sha256": "0" * 64, "bytes": 0, "script_hashes": []},
                },
            }
        ),
    ]:
        (root / MANIFEST_NAME).write_text(raw)
        app = create_app(Settings(data_dir=tmp_path / "more"), port=PORT, workbench_dir=root)
        assert signed_in(app).get("/").status_code == 503


def test_a_missing_export_does_not_break_the_api(tmp_path: Path) -> None:
    app = create_app(
        Settings(data_dir=tmp_path / "data"), port=PORT, workbench_dir=tmp_path / "missing"
    )
    client = signed_in(app)
    assert client.get("/").status_code == 404
    assert client.get("/api/runs/missing").status_code == 404


def test_hardlinked_asset_is_refused_without_reading_it(
    exported: tuple[FastAPI, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, root = exported
    original = root / "fonts/license.txt"
    os.link(original, tmp_path / "outside.txt")

    def unread(*args: object) -> bytes:
        pytest.fail("must refuse the hardlink before reading")

    monkeypatch.setattr("backend.workbench.read_contained", unread)
    assert signed_in(app).get("/fonts/license.txt").status_code == 503


def test_file_swapped_between_check_and_open_is_never_read(
    exported: tuple[FastAPI, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = exported
    outside = tmp_path / "different.txt"
    outside.write_text("outside bytes must never be read")
    original_open = os.open

    def swapped(path: object, flags: int) -> int:
        return original_open(outside, flags)

    def unread(*args: object) -> bytes:
        pytest.fail("must check the opened file identity before reading")

    monkeypatch.setattr("analysis.snapshot.os.open", swapped)
    monkeypatch.setattr("analysis.snapshot.os.read", unread)
    assert signed_in(app).get("/fonts/license.txt").status_code == 503

"""Offline source observations and hostile input regressions; no target execution."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis.advisories import (
    MAX_BYTES,
    PACK,
    PIN,
    Affected,
    compare,
    import_pack,
    load_pack,
    selected_pack,
)
from analysis.security_signals import configuration, lock_packages, observe
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.signals import SignalSet
from backend.settings import Settings

TODAY = date(2026, 10, 7)
HASH = json.loads(PIN.read_bytes())["sha256"]


def capture(tmp_path: Path, files: dict[str, str]) -> tuple[SignalSet, SnapshotStore]:
    root = tmp_path / "target"
    root.mkdir()
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    settings = Settings(data_dir=tmp_path / "data")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    snapshot = take_snapshot(root, store)
    return observe(snapshot, store, settings, "review-" + "b" * 32), store


def npm(base_version: str, **extra: object) -> str:
    return json.dumps(
        {
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "root"},
                "node_modules/alias": {
                    "name": "react-server-dom-webpack",
                    "version": base_version,
                    "resolved": "https://registry.npmjs.org/react-server-dom-webpack/-/react-server-dom-webpack-"
                    + base_version
                    + ".tgz",
                    **extra,
                },
            },
        }
    )


def test_credential_shapes_never_publish_values_or_read_excluded_secrets(tmp_path: Path) -> None:
    token = "ghp_" + "Z" * 34
    result, store = capture(
        tmp_path,
        {
            "source.py": f'api_key = "{token}"\n',
            ".env": 'password="excluded-value"\n',
            "README.md": 'password="synthetic-only"\n',
        },
    )
    encoded = result.model_dump_json()
    assert (
        token not in encoded and "synthetic-only" not in encoded and "excluded-value" not in encoded
    )
    assert result.signals and all(s.fingerprint for s in result.signals)
    assert all(s.category == "secret" and "[REDACTED]" in s.summary for s in result.signals)
    snapshot = store.load(result.snapshot_id)
    assert ".env" not in [f.path for f in snapshot.files]
    assert any("1 known secret files" in text for text in result.limitations)
    assert hashlib.sha256(token.encode()).hexdigest() not in encoded


@pytest.mark.parametrize(
    "source,expected",
    [
        ("from fastapi import FastAPI as App\na=App(debug=True)\n", ["config-fastapi-debug"]),
        ("import httpx as h\nclient=h.Client(verify=False)\n", ["config-httpx-tls"]),
        ("from httpx import AsyncClient as C\nclient=C(verify=False)\n", ["config-httpx-tls"]),
        ("from fastapi import FastAPI\na=FastAPI(debug=False)\n", []),
        ("from httpx import Client\na=Client(verify=True)\n", []),
        ('# FastAPI(debug=True)\n"Client(verify=False)"\n', []),
        ("from unrelated import FastAPI\na=FastAPI(debug=True)\n", []),
        ("from fastapi import FastAPI\nFastAPI=other\na=FastAPI(debug=True)\n", []),
        ("from fastapi import FastAPI\ndef f(FastAPI):\n return FastAPI(debug=True)\n", []),
        ("import httpx\nhttpx.Client=other\na=httpx.Client(verify=False)\n", []),
        ("from fastapi import FastAPI\na=FastAPI(debug=flag)\n", []),
        ("from fastapi import FastAPI\na=FastAPI(debug=True, **options)\n", []),
        ("from fastapi import FastAPI\nfrom other import FastAPI\na=FastAPI(debug=True)\n", []),
    ],
)
def test_config_binds_executable_imports_and_refuses_shadowing(
    source: str, expected: list[str]
) -> None:
    assert [r for r, _, _ in configuration(source)] == expected


@pytest.mark.parametrize(
    "ecosystem,a,b,result",
    [
        ("npm", "1.0.0-alpha.2", "1.0.0-alpha.11", -1),
        ("npm", "1.0.0-1", "1.0.0-a", -1),
        ("npm", "1.0.0-alpha", "1.0.0-alpha.1", -1),
        ("npm", "1.0.0-rc.1", "1.0.0", -1),
        ("npm", "1.0.0+one", "1.0.0+two", 0),
        ("PyPI", "1!1.0", "2.0", 1),
        ("PyPI", "1.0.dev1", "1.0a1", -1),
        ("PyPI", "1.0rc1", "1.0", -1),
        ("PyPI", "1.0.post1", "1.0", 1),
        ("PyPI", "1.0+local", "1.0", 1),
        ("PyPI", "1.0", "1.0.0", 0),
    ],
)
def test_ecosystem_ordering(ecosystem: str, a: str, b: str, result: int) -> None:
    assert compare(ecosystem, a, b) == result


@pytest.mark.parametrize("version", ["^1.0.0", "1.0", "01.0.0", "1.0.0-01", "file:1.0.0"])
def test_ranges_are_not_exact_npm_versions(version: str) -> None:
    with pytest.raises(ValueError):
        compare("npm", version, version)


def test_real_pack_preserves_pinned_sources_and_release_boundaries() -> None:
    pack = load_pack(PACK, HASH, today=TODAY)
    for record in pack.records:
        source = PACK.parent / "sources" / f"{record.id}.json"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record.source_sha256
        original = json.loads(source.read_bytes())
        assert [a.ranges for a in record.affected] == [
            Affected(
                ecosystem=a["package"]["ecosystem"],
                name=a["package"]["name"],
                ranges=a["ranges"],
                versions=a.get("versions", []),
            ).ranges
            for a in original["affected"]
        ]
    rsc = pack.records[0]
    assert any(a.contains("19.1.1") for a in rsc.affected)
    assert not any(a.contains("19.1.2") for a in rsc.affected)
    requests = pack.records[1].affected[0]
    assert requests.contains("2.31.0") and not requests.contains("2.32.0")
    assert requests.contains("2.32.0rc1")


def test_osv_inclusive_last_affected_exclusive_limit_and_multiple_intervals() -> None:
    # Synthetic range semantics only: no synthetic advisory record or accuracy claim.
    affected = Affected.model_validate(
        dict(
            ecosystem="npm",
            name="range-fixture",
            ranges=[
                {
                    "type": "SEMVER",
                    "events": [
                        {"introduced": "0"},
                        {"last_affected": "1.0.0"},
                        {"introduced": "2.0.0"},
                        {"limit": "3.0.0"},
                    ],
                },
            ],
            versions=["4.0.0"],
        )
    )
    assert affected.contains("0.0.1") and affected.contains("1.0.0")
    assert not affected.contains("1.0.1")
    assert affected.contains("2.1.0") and not affected.contains("3.0.0")
    assert affected.contains("4.0.0")


@pytest.mark.parametrize(
    "changes",
    [
        {"license": "unknown"},
        {"schema_version": "OSV-unchecked"},
        {"snapshot_date": "2026-06-01"},
        {"snapshot_date": "2099-01-01"},
        {"publisher": "Target manifest"},
    ],
)
def test_invalid_or_stale_pack_does_not_replace_active_selection(
    tmp_path: Path, changes: dict[str, str]
) -> None:
    import_pack(PACK, HASH, tmp_path)
    active = (tmp_path / "advisories/active.json").read_bytes()
    invalid = {**json.loads(PACK.read_bytes()), **changes}
    data = json.dumps(invalid).encode()
    source = tmp_path / "bad.json"
    source.write_bytes(data)
    with pytest.raises(ValueError):
        import_pack(source, hashlib.sha256(data).hexdigest(), tmp_path)
    assert (tmp_path / "advisories/active.json").read_bytes() == active
    assert selected_pack(tmp_path)[1] == HASH


def test_modified_oversized_or_malformed_pack_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_pack(PACK, "0" * 64, today=TODAY)
    with pytest.raises(ValueError):
        load_pack(PACK, HASH, today=TODAY + timedelta(days=91))
    source = tmp_path / "big.json"
    source.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError):
        load_pack(source, HASH, today=TODAY)
    payload = json.loads(PACK.read_bytes())
    payload["records"][0]["affected"][0]["ranges"][0]["events"] = [{"fixed": "19.0.1"}]
    data = json.dumps(payload).encode()
    source.write_bytes(data)
    with pytest.raises(ValidationError):
        load_pack(source, hashlib.sha256(data).hexdigest(), today=TODAY)


def test_lockfile_alias_and_pypi_normalization(tmp_path: Path) -> None:
    assert lock_packages("package-lock.json", npm("19.1.1").encode()) == [
        ("npm", "react-server-dom-webpack", "19.1.1")
    ]
    uv = 'version = 1\n[[package]]\nname = "Requests"\nversion = "2.31.0"\nsource = {registry = "https://pypi.org/simple"}\n'
    result, _ = capture(tmp_path, {"uv.lock": uv, "package-lock.json": npm("19.1.1")})
    assert {s.package for s in result.signals} == {"requests", "react-server-dom-webpack"}
    assert {s.advisory_id for s in result.signals} == {"GHSA-fv66-9v8q-g76r", "GHSA-9wx4-h78v-vm56"}


@pytest.mark.parametrize(
    "extra",
    [
        {"resolved": "file:../project"},
        {"resolved": "https://registry.npmjs.org/unrelated/-/a.tgz"},
        {"resolved": "https://private.invalid/package.tgz"},
        {"link": True},
        {"version": "^19.1.1"},
        {"version": None},
    ],
)
def test_ambiguous_package_sources_never_imply_known_versions(extra: dict[str, object]) -> None:
    assert lock_packages("package-lock.json", npm("19.1.1", **extra).encode())[0][2] is None


@pytest.mark.parametrize(
    "content",
    [
        '{"lockfileVersion":3,"lockfileVersion":2,"packages":{}}',
        '{"lockfileVersion":3,"packages":{"../../outside":{"version":"19.1.1"}}}',
        '{"lockfileVersion":3,"packages":[]}',
        "[]",
        "{invalid",
        '{"lockfileVersion":3,"packages":{"node_modules/x":null}}',
        "[" * 2000 + "]" * 2000,
    ],
)
def test_hostile_lockfiles_are_bounded_and_refused(content: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        lock_packages("package-lock.json", content.encode())


def test_parse_failure_stale_pack_and_unsupported_lock_are_explicit_gaps(tmp_path: Path) -> None:
    result, _ = capture(
        tmp_path, {"package-lock.json": "{invalid", "pnpm-lock.yaml": "lockfileVersion: 9"}
    )
    assert result.status == "partial" and not result.signals
    assert any("malformed" in text for text in result.limitations)
    assert any("unsupported lockfiles" in text for text in result.limitations)
    settings = Settings(data_dir=tmp_path / "data")
    active = settings.data_dir / "advisories/active.json"
    active.parent.mkdir(parents=True)
    active.write_text('{"sha256":"' + "0" * 64 + '"}', encoding="utf-8")
    snapshot = SnapshotStore(settings.cache_dir / "snapshots").load(result.snapshot_id)
    rerun = observe(
        snapshot, SnapshotStore(settings.cache_dir / "snapshots"), settings, result.run_id
    )
    assert rerun.pack_sha256 is None and any(
        "pack unavailable" in text for text in rerun.limitations
    )


def test_observation_limit_records_incomplete_scope(tmp_path: Path) -> None:
    result, _ = capture(
        tmp_path, {"many.py": "\n".join(f'api_key="synthetic-{n}"' for n in range(110))}
    )
    assert len(result.signals) == 100 and result.status == "partial"
    assert any("Signal limit" in text for text in result.limitations)


def test_unknown_version_is_observed_as_unknown_without_publishing_specifier(
    tmp_path: Path,
) -> None:
    result, _ = capture(tmp_path, {"package-lock.json": npm("19.1.1", version="^19.1.1")})
    assert len(result.signals) == 1
    item = result.signals[0]
    assert item.status == "unknown" and item.version is None and item.advisory_id is None
    assert "^19.1.1" not in result.model_dump_json()


def test_nested_scoped_packages_and_withdrawn_real_record(tmp_path: Path) -> None:
    lock = json.dumps(
        {
            "lockfileVersion": 2,
            "packages": {
                "node_modules/parent/node_modules/@scope/pkg": {
                    "version": "1.2.3",
                    "resolved": "https://registry.npmjs.org/@scope/pkg/-/pkg-1.2.3.tgz",
                },
            },
        }
    )
    assert lock_packages("package-lock.json", lock.encode()) == [("npm", "@scope/pkg", "1.2.3")]
    pack = json.loads(PACK.read_bytes())
    pack["records"][0]["withdrawn"] = "2026-10-07T00:00:00Z"
    source = tmp_path / "withdrawn.json"
    data = json.dumps(pack).encode()
    source.write_bytes(data)
    import_pack(source, hashlib.sha256(data).hexdigest(), tmp_path / "data")
    result, _ = capture(tmp_path, {"package-lock.json": npm("19.1.1")})
    assert not result.signals

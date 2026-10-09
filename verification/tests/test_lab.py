"""Admission tests never execute candidate code; live acceptance is recorded separately."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from verification.lab import LAB, WORKER, LabUnavailable, admit, receipt_spec, verified_files


def copied(tmp_path: Path) -> Path:
    files, _ = verified_files()
    root = tmp_path / "api"
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def test_pins_are_valid_and_copy_contains_only_verified_bytes(tmp_path: Path) -> None:
    root = copied(tmp_path)
    original, manifest = verified_files()
    assert verified_files(root) == (original, manifest)
    assert len(manifest) == 64


@pytest.mark.parametrize("name", ["tandir/routers/orders.py", "tandir/security.py", "uv.lock"])
def test_any_pinned_source_change_refuses_execution(tmp_path: Path, name: str) -> None:
    root = copied(tmp_path)
    source = root / name
    source.write_bytes(source.read_bytes() + b"\n# altered\n")
    with pytest.raises(LabUnavailable, match="release manifest"):
        verified_files(root)


@pytest.mark.parametrize("invoice", [False, True])
def test_only_reviewed_templates_are_admitted(invoice: bool) -> None:
    admit(receipt_spec("PLUMB_TEST_123", invoice=invoice))


@pytest.mark.parametrize(
    "path", ["/orders/1/photos?name=../../private", "/kitchen/orders/1/items/1/label", "/auth/me"]
)
def test_arbitrary_paths_are_not_admitted_on_the_host(path: str) -> None:
    spec = receipt_spec("PLUMB_TEST_123")
    request = spec.requests[1].model_copy(update={"path": path})
    with pytest.raises(LabUnavailable, match="reviewed"):
        admit(spec.model_copy(update={"requests": [spec.requests[0], request, spec.requests[2]]}))


def test_arbitrary_body_and_capture_cannot_reach_host_runner() -> None:
    spec = receipt_spec("PLUMB_TEST_123")
    setup = spec.requests[0].model_copy(
        update={"body": {"script": "payload"}, "capture": {"victim": "id"}}
    )
    with pytest.raises(LabUnavailable):
        admit(spec.model_copy(update={"requests": [setup, *spec.requests[1:]]}))


def test_worker_refuses_extra_importable_code_before_it_runs(tmp_path: Path) -> None:
    root = copied(tmp_path)
    marker = tmp_path / "executed.txt"
    # This fixture is never imported: the trusted worker refuses the extra file set.
    (root / "sqlalchemy.py").write_text(f"raise RuntimeError({str(marker)!r})\n")
    python = LAB / "api/.venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    result = subprocess.run(  # noqa: S603 - fixed trusted worker refuses candidate before imports
        [str(python), "-I", str(WORKER), str(root), str(tmp_path / "data")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "pinned file set" in result.stderr
    assert not marker.exists() and not (tmp_path / "data").exists()


def test_probe_spec_roundtrip_retains_exact_admission() -> None:
    from backend.contracts.verification import ProbeSpec

    spec = receipt_spec("PLUMB_TEST_123")
    admit(ProbeSpec.model_validate_json(spec.model_dump_json()))
    assert json.loads(spec.model_dump_json())["requests"][0]["capture"] == {"order_id": "id"}

"""Admission and lifecycle for Plumb's hash-pinned bundled Tandir API (§3.4)."""

import difflib
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import psutil

from analysis.paths import resolve_inside
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.verification import (
    Access,
    HTTPProbeRequest,
    ProbeRun,
    ProbeSpec,
    RunnerKind,
    SnapshotRole,
    StepRole,
)
from backend.settings import Settings
from verification.probes import execute

REPOSITORY = Path(__file__).resolve().parents[1]
LAB = REPOSITORY / "labs/tandir"
PIN = Path(__file__).with_name("pins") / "tandir-api.json"
WORKER = Path(__file__).with_name("lab_worker.py")
PATCH = Path(__file__).with_name("pins") / "receipt.patch"
Variant = Literal["vulnerable", "receipt_fixed"]
RECEIPT_PATH = "tandir/routers/orders.py"
RECEIPT_BEFORE = (
    "    order = db.get(Order, order_id)\n"
    "    if order is None:\n"
    '        raise HTTPException(status_code=404, detail="Order not found")\n'
    "    return ReceiptOut.from_order(order)\n"
)
RECEIPT_AFTER = (
    "    order = load_order_scoped(db, order_id, user)\n    return ReceiptOut.from_order(order)\n"
)


class LabUnavailable(ValueError):
    pass


def verified_files(
    root: Path = LAB / "api", *, variant: Variant = "vulnerable"
) -> tuple[dict[str, bytes], str]:
    """Verify every byte before copying; never import or execute the supplied root."""
    raw = PIN.read_bytes()
    pin = json.loads(raw)
    files = {}
    for path, expected in pin["files"].items():
        source = resolve_inside(root, path)
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise LabUnavailable("Bundled lab differs from its release manifest; execution refused")
        files[path] = content
    if hashlib.sha256(WORKER.read_bytes()).hexdigest() != pin["worker_sha256"]:
        raise LabUnavailable("Trusted lab worker differs from its release manifest")
    python = LAB / "api/.venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if (
        not python.is_file()
        or hashlib.sha256(python.read_bytes()).hexdigest() != pin["python_sha256"]
    ):
        raise LabUnavailable("Trusted lab interpreter differs from its local release manifest")
    if variant != "vulnerable":
        if variant != "receipt_fixed":
            raise LabUnavailable("Unknown bundled release variant")
        approved = pin["variants"][variant]
        patch = PATCH.read_bytes()
        if hashlib.sha256(patch).hexdigest() != approved["patch_sha256"]:
            raise LabUnavailable("Receipt patch differs from its release manifest")
        original = files[RECEIPT_PATH].decode("utf-8")
        if original.count(RECEIPT_BEFORE) != 1:
            raise LabUnavailable("Receipt patch preimage is not unique")
        changed = original.replace(RECEIPT_BEFORE, RECEIPT_AFTER, 1)
        derived = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                changed.splitlines(keepends=True),
                fromfile="a/api/" + RECEIPT_PATH,
                tofile="b/api/" + RECEIPT_PATH,
            )
        ).encode("utf-8")
        if patch != derived or set(approved["files"]) != {RECEIPT_PATH}:
            raise LabUnavailable("Only the exact reviewed receipt diff is admitted")
        files[RECEIPT_PATH] = changed.encode("utf-8")
        if hashlib.sha256(files[RECEIPT_PATH]).hexdigest() != approved["files"][RECEIPT_PATH]:
            raise LabUnavailable("Patched receipt differs from its release manifest")
    return files, hashlib.sha256(raw).hexdigest()


def receipt_spec(
    marker: str, *, invoice: bool = False, finding_id: str = "finding:lab-receipt"
) -> ProbeSpec:
    path = "/orders/{order_id}/" + ("invoice" if invoice else "receipt")
    return ProbeSpec(
        id="probe:lab-invoice" if invoice else "probe:lab-receipt",
        finding_id=finding_id,
        marker=marker,
        requests=[
            HTTPProbeRequest(
                role=StepRole.SETUP,
                principal="alice",
                method="POST",
                path="/orders",
                body={
                    "branch_id": 1,
                    "delivery_address": "{marker}",
                    "items": [{"menu_item_id": 1, "quantity": 1}],
                },
                capture={"order_id": "id"},
                expected_if_safe=Access.ALLOWED,
            ),
            HTTPProbeRequest(
                role=StepRole.ATTACK,
                principal="bob",
                method="GET",
                path=path,
                expected_if_safe=Access.DENIED,
            ),
            HTTPProbeRequest(
                role=StepRole.CONTROL,
                principal="alice",
                method="GET",
                path=path,
                expected_if_safe=Access.ALLOWED,
            ),
        ],
    )


def admit(spec: ProbeSpec) -> None:
    # Host-side bundled execution has a deliberately small, reviewed request surface.
    # Arbitrary declarative paths/bodies require an isolated runner, not this exception.
    if not any(
        spec == receipt_spec(spec.marker, invoice=invoice, finding_id=spec.finding_id)
        for invoice in (False, True)
    ):
        raise LabUnavailable("Bundled runner admits only reviewed receipt/invoice templates")


@contextmanager
def launch(
    files: dict[str, bytes], settings: Settings, *, variant: Variant = "vulnerable"
) -> Iterator[tuple[str, httpx.Client]]:
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() in {"llama-server.exe", "llama-server"}:
                raise LabUnavailable("Stop inference before running the bundled lab")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    python = LAB / "api/.venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        raise LabUnavailable("The trusted lab's locked environment is not installed")
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lab-probe-", dir=settings.cache_dir) as folder:
        work = Path(folder).resolve()
        source, data = work / "api", work / "data"
        for path, content in files.items():
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
        process = subprocess.Popen(  # noqa: S603 - fixed trusted interpreter/worker; verified source
            [str(python), "-I", str(WORKER), str(source), str(data), variant],
            cwd=work,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        ready: queue.Queue[str] = queue.Queue(maxsize=1)

        def read_ready() -> None:
            if process.stdout is not None:
                ready.put(process.stdout.readline(1024))

        reader = threading.Thread(target=read_ready, daemon=True)
        reader.start()
        try:
            try:
                handshake = json.loads(ready.get(timeout=25))
                port = handshake["port"]
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError("invalid readiness port")
            except (queue.Empty, ValueError, KeyError, TypeError) as error:
                raise LabUnavailable("Verified bundled lab did not become ready") from error
            origin = f"http://127.0.0.1:{port}"
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
                # Wait for uvicorn after the child has reserved its exclusive socket.
                for _ in range(100):
                    try:
                        if client.get(origin + "/health", timeout=0.2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        if process.poll() is not None:
                            raise LabUnavailable("Bundled lab exited before readiness") from None
                        time.sleep(0.025)
                else:
                    raise LabUnavailable("Bundled lab readiness failed")
                yield origin, client
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            reader.join(timeout=1)


def run(spec: ProbeSpec, settings: Settings | None = None) -> ProbeRun:
    settings = settings or Settings()
    admit(spec)
    files, manifest = verified_files()
    snapshot = take_snapshot(LAB, SnapshotStore(settings.cache_dir / "snapshots"))
    return _probe(spec, settings, files, manifest, snapshot.id, "vulnerable")


def run_release(spec: ProbeSpec, settings: Settings, *, variant: Variant) -> ProbeRun:
    """Probe one exact API release copy; replay snapshots have the same path domain."""
    admit(spec)
    files, manifest = verified_files(variant=variant)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lab-release-", dir=settings.cache_dir) as folder:
        root = Path(folder) / "tandir-api"
        for path, content in files.items():
            target = root / "api" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "replay-snapshots"))
    return _probe(spec, settings, files, manifest, snapshot.id, variant)


def _probe(
    spec: ProbeSpec,
    settings: Settings,
    files: dict[str, bytes],
    manifest: str,
    snapshot_id: str,
    variant: Variant,
) -> ProbeRun:
    with launch(files, settings, variant=variant) as (origin, client):
        headers = {}
        for user in ("alice", "bob"):
            login = client.post(
                origin + "/auth/login", json={"username": user, "password": user + "-lab-pass"}
            )
            if login.status_code != 200:
                raise LabUnavailable("Lab fixture sign-in failed")
            token = login.json().get("token")
            if not isinstance(token, str) or not token:
                raise LabUnavailable("Lab fixture sign-in returned no token")
            headers[user] = {"authorization": "Bearer " + token}
        return execute(
            spec,
            client=client,
            origin=origin,
            headers=headers,
            snapshot_id=snapshot_id,
            manifest_sha256=manifest,
            runner=RunnerKind.BUNDLED_LAB,
            snapshot_role=SnapshotRole.PATCHED
            if variant == "receipt_fixed"
            else SnapshotRole.VULNERABLE,
            run_id="probe-run:" + uuid4().hex,
        )

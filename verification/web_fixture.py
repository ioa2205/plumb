"""Start Plumb's own synthetic website fixture, after checking every byte (ADR-0028).

The fixture is trusted Plumb code, not analyzed code: standard library only,
pinned by hash, copied to a temporary folder and run there with the current
interpreter in isolated mode. It needs neither Tandir's environment nor any
developer tool, so the portable package can run it too.

Passwords and the label marker are invented for each start and exist only in
memory: in this process and in the fixture's.

    uv run python -m verification.web_fixture check   # do the files match the pin?
    uv run python -m verification.web_fixture pin     # rewrite the pin after a reviewed change
"""

import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from backend.contracts.assessment import ScopeAuthority
from backend.contracts.web import (
    ActionClass,
    LoginConfig,
    OwnerRule,
    SignupConfig,
    WebAccount,
    WebBudget,
    WebObject,
    WebsiteScope,
    WebTarget,
)
from backend.settings import Settings
from verification.web_secrets import SecretStore

REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "labs" / "chorsu"
PIN = Path(__file__).with_name("pins") / "chorsu.json"
FILES = ("server.py", "static/app.js", "static/style.css")
PORTS = {"open": 8711, "defended": 8712}
SUPPORT = "help@chorsu-lockers.test"
Variant = Literal["open", "defended"]


class FixtureUnavailable(ValueError):
    pass


def _hashes(root: Path = FIXTURE) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in FILES}


def verified_files(root: Path | None = None) -> tuple[dict[str, bytes], str]:
    """Every fixture file, only if all of them match the pin. Nothing is imported."""
    root = root or FIXTURE
    try:
        raw = PIN.read_bytes()
        pin = json.loads(raw)
        files = {name: (root / name).read_bytes() for name in FILES}
    except (OSError, ValueError) as error:
        raise FixtureUnavailable("The website fixture or its pin cannot be read.") from error
    if set(pin.get("files", {})) != set(FILES) or any(
        hashlib.sha256(content).hexdigest() != pin["files"][name] for name, content in files.items()
    ):
        raise FixtureUnavailable("The website fixture differs from its pin; it was not started.")
    return files, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Fixture:
    variant: Variant
    origin: str
    port: int
    manifest_sha256: str
    marker: str
    secrets: SecretStore  # passwords for dilnoza and rustam, by reference
    boundary: int | None = None

    def scope(
        self,
        *,
        website_id: str = "chorsu-fixture",
        minutes: int = 60,
        signup: bool = True,
        budget: WebBudget | None = None,
    ) -> WebsiteScope:
        """The owned scope a journey on this fixture is approved for."""
        now = datetime.now(UTC)
        accounts = [
            WebAccount(
                account_id="dilnoza",
                role="customer",
                label="Dilnoza (synthetic customer)",
                username="dilnoza",
                secret_ref="chorsu-dilnoza",  # noqa: S106 - a reference name, not a secret
            ),
            WebAccount(
                account_id="rustam",
                role="customer",
                label="Rustam (synthetic customer)",
                username="rustam",
                secret_ref="chorsu-rustam",  # noqa: S106 - a reference name, not a secret
            ),
        ]
        actions: list[ActionClass] = ["read", "sign_in", "compare", "report"]
        if signup:
            actions.append("sign_up")
            accounts.append(
                WebAccount(
                    account_id="newcomer",
                    role="customer",
                    label="Newcomer (created by the approved sign-up)",
                    username="plumb" + secrets.token_hex(4),
                    secret_ref="chorsu-newcomer",  # noqa: S106 - a reference name
                    provisioned=False,
                    contact_email="newcomer@chorsu.test",
                )
            )
        return WebsiteScope(
            scope_id="scope-" + secrets.token_hex(6),
            website_id=website_id,
            name="Chorsu Parcel Lockers (owned fixture, " + self.variant + ")",
            mode="owned_fixture",
            targets=[WebTarget(origin=self.origin, paths=["/"])],
            start_path="/",
            purpose="Check who can read a parcel and its pickup label on Plumb's own fixture.",
            authority=ScopeAuthority(
                granted_by="Plumb fixture owner",
                reference="Owned synthetic fixture; manifest " + self.manifest_sha256[:16],
                granted_at=now - timedelta(seconds=1),
            ),
            accounts=accounts,
            objects=[
                WebObject(
                    object_id="parcel-4117-label",
                    owner_account_id="dilnoza",
                    kind="pickup label of parcel 4117",
                    path="/api/parcels/4117/label",
                    marker=self.marker,
                ),
                WebObject(
                    object_id="parcel-4117",
                    owner_account_id="dilnoza",
                    kind="parcel 4117",
                    path="/api/parcels/4117",
                ),
            ],
            rules=[
                OwnerRule(
                    rule_id="rule-label-owner-only",
                    statement="Only the customer a parcel belongs to may read its pickup label.",
                    object_id="parcel-4117-label",
                    allowed_account_ids=["dilnoza"],
                    declared_by="Plumb fixture owner",
                    basis="Fixture design: a pickup label opens the locker.",
                ),
                OwnerRule(
                    rule_id="rule-parcel-owner-only",
                    statement="Only the customer a parcel belongs to may read the parcel.",
                    object_id="parcel-4117",
                    allowed_account_ids=["dilnoza"],
                    declared_by="Plumb fixture owner",
                    basis="Fixture design.",
                ),
            ],
            allowed_actions=actions,
            login=LoginConfig(path="/signin", success_path="/parcels", success_text="Signed in as"),
            signup=SignupConfig(
                path="/join",
                approved_side_effects=["Creates one synthetic customer account in the fixture."],
                sends_messages=False,
                success_text="Signed in as",
            )
            if signup
            else None,
            expires_at=now + timedelta(minutes=minutes),
            budget=budget or WebBudget(),
            stop_conditions=[
                "Unexpected personal data appears.",
                "Any request would leave the fixture's origin.",
            ],
            public_values=[SUPPORT],
            confirmed_targets=True,
        )


@contextmanager
def launch(
    variant: Variant,
    settings: Settings | None = None,
    *,
    port: int | None = None,
    boundary: int | None = None,
) -> Iterator[Fixture]:
    """Run the verified fixture on loopback for the ``with`` block.

    ``port`` None uses the variant's declared port; 0 lets the system choose
    (tests). ``boundary`` adds the pages that try to reach that other port.
    """
    files, manifest = verified_files()
    settings = settings or Settings()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    store = SecretStore()
    store.put("chorsu-dilnoza", "Fx-" + secrets.token_urlsafe(18))
    store.put("chorsu-rustam", "Fx-" + secrets.token_urlsafe(18))
    marker = "CHORSU-LBL-" + secrets.token_hex(6).upper()
    with tempfile.TemporaryDirectory(prefix="chorsu-", dir=settings.cache_dir) as folder:
        work = Path(folder).resolve()
        for name, content in files.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        argv = [
            sys.executable,
            "-I",
            str(work / "server.py"),
            "--variant",
            variant,
            "--port",
            str(PORTS[variant] if port is None else port),
        ]
        if boundary is not None:
            argv += ["--boundary", str(boundary)]
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ}
        process = subprocess.Popen(  # noqa: S603 - current interpreter; hash-verified own fixture
            argv,
            cwd=work,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        ready: queue.Queue[str] = queue.Queue(maxsize=1)
        reader = threading.Thread(
            target=lambda: ready.put(process.stdout.readline(1024) if process.stdout else ""),
            daemon=True,
        )
        try:
            if process.stdin is None:
                raise FixtureUnavailable("The website fixture could not be started.")
            process.stdin.write(
                json.dumps(
                    {
                        "accounts": {
                            "dilnoza": store.get("chorsu-dilnoza"),
                            "rustam": store.get("chorsu-rustam"),
                        },
                        "marker": marker,
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            reader.start()
            try:
                handshake = json.loads(ready.get(timeout=20))
                bound = handshake["port"]
                if type(bound) is not int or not 1 <= bound <= 65535:
                    raise ValueError("invalid port")
            except (queue.Empty, ValueError, KeyError, TypeError) as error:
                raise FixtureUnavailable(
                    "The website fixture did not become ready (is its port in use?)."
                ) from error
            yield Fixture(
                variant=variant,
                origin=f"http://127.0.0.1:{bound}",
                port=bound,
                manifest_sha256=manifest,
                marker=marker,
                secrets=store,
                boundary=boundary,
            )
        finally:
            store.clear()
            if process.stdin is not None:
                with suppress(OSError):
                    process.stdin.close()  # the fixture stops when its input ends
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if reader.is_alive():
                reader.join(timeout=1)


def main(argv: list[str] | None = None) -> int:
    command = (argv if argv is not None else sys.argv[1:]) or ["check"]
    if command == ["pin"]:
        PIN.parent.mkdir(parents=True, exist_ok=True)
        PIN.write_text(
            json.dumps({"fixture": "chorsu", "files": _hashes()}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Pinned {len(FILES)} fixture files in {PIN}")
        return 0
    if command == ["check"]:
        try:
            _, manifest = verified_files()
        except FixtureUnavailable as error:
            print(str(error))
            return 1
        print(f"Website fixture matches its pin (manifest {manifest[:16]}).")
        return 0
    print("Use: python -m verification.web_fixture check | pin")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

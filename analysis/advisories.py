"""Bounded offline OSV pack verification and ecosystem version ordering.

Import is an explicit local operation. Review has no HTTP client and never reads
a pack from the target. Unsupported range forms refuse the pack, not guess.
"""

import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Self

from packaging.version import Version
from pydantic import AwareDatetime, Field, model_validator

from backend.contracts.common import Contract, Id, Sha256
from backend.settings import Settings

VERSION = "offline-osv-1"
MAX_BYTES = 2 * 1024 * 1024
MAX_AGE_DAYS = 90
PACK_DIR = Path(__file__).with_name("advisory_pack")
PACK = PACK_DIR / "pack.json"
PIN = PACK_DIR / "pin.json"


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def json_data(data: bytes) -> Any:  # noqa: ANN401 - untrusted JSON input
    if len(data) > MAX_BYTES:
        raise ValueError("JSON size limit")
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("invalid bounded JSON") from error


def bounded_bytes(path: Path) -> bytes:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("advisory input size limit")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("advisory input size limit")
    return data


class Semver(Contract):
    major: int
    minor: int
    patch: int
    pre: tuple[str, ...] = ()

    def compare(self, other: "Semver") -> int:
        a, b = (self.major, self.minor, self.patch), (other.major, other.minor, other.patch)
        if a != b:
            return (a > b) - (a < b)
        if not self.pre or not other.pre:
            return int(not self.pre) - int(not other.pre)
        for left, right in zip(self.pre, other.pre, strict=False):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return (int(left) > int(right)) - (int(left) < int(right))
            if left.isdigit() != right.isdigit():
                return int(right.isdigit()) - int(left.isdigit())
            return (left > right) - (left < right)
        return (len(self.pre) > len(other.pre)) - (len(self.pre) < len(other.pre))


def semver(text: str) -> Semver:
    match = re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?",
        text,
    )
    if not match or len(text) > 100:
        raise ValueError("not an exact SemVer version")
    pre = tuple(match[4].split(".")) if match[4] else ()
    if any(p.isdigit() and len(p) > 1 and p.startswith("0") for p in pre):
        raise ValueError("noncanonical numeric prerelease")
    return Semver(major=int(match[1]), minor=int(match[2]), patch=int(match[3]), pre=pre)


def compare(ecosystem: str, left: str, right: str) -> int:
    if ecosystem == "npm":
        return semver(left).compare(semver(right))
    elif ecosystem == "PyPI":
        x, y = Version(left), Version(right)
        return (x > y) - (x < y)
    else:
        raise ValueError("unsupported ecosystem")


def package_name(ecosystem: str, name: str) -> str:
    if ecosystem == "PyPI" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", name):
        return re.sub(r"[-_.]+", "-", name).lower()
    if (
        ecosystem == "npm"
        and re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", name)
        and len(name) <= 200
        and not any(part in {".", ".."} for part in name.split("/"))
    ):
        return name
    raise ValueError("invalid package identity")


class Event(Contract):
    introduced: str | None = None
    fixed: str | None = None
    last_affected: str | None = None
    limit: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if sum(v is not None for v in self.model_dump().values()) != 1:
            raise ValueError("OSV event has exactly one boundary")
        return self


class Range(Contract):
    type: Literal["SEMVER", "ECOSYSTEM"]
    events: list[Event] = Field(min_length=1, max_length=100)


class Affected(Contract):
    ecosystem: Literal["npm", "PyPI"]
    name: str
    ranges: list[Range] = Field(default=[], max_length=100)
    versions: list[str] = Field(default=[], max_length=2000)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        package_name(self.ecosystem, self.name)
        for version in self.versions:
            compare(self.ecosystem, version, version)
        for interval in self.ranges:
            if interval.type != ("SEMVER" if self.ecosystem == "npm" else "ECOSYSTEM"):
                raise ValueError("range ordering must match its ecosystem")
            active = False
            previous: str | None = None
            for event in interval.events:
                kind, value = next((k, v) for k, v in event.model_dump().items() if v is not None)
                if kind == "introduced":
                    if active or (value == "0" and previous is not None):
                        raise ValueError("unordered introduction")
                    active = True
                elif not active:
                    raise ValueError("range closes without introduction")
                else:
                    active = False
                if value != "0" or kind != "introduced":
                    compare(self.ecosystem, value, value)
                    if previous is not None and compare(self.ecosystem, previous, value) >= 0:
                        raise ValueError("range boundaries must increase")
                    previous = value
        if not self.ranges and not self.versions:
            raise ValueError("missing affected versions")
        return self

    def contains(self, version: str) -> bool:
        compare(self.ecosystem, version, version)
        if any(compare(self.ecosystem, version, listed) == 0 for listed in self.versions):
            return True
        for interval in self.ranges:
            active = False
            for event in interval.events:
                if event.introduced is not None:
                    active = (
                        event.introduced == "0"
                        or compare(self.ecosystem, version, event.introduced) >= 0
                    )
                else:
                    boundary = event.fixed or event.limit or event.last_affected
                    if boundary is None:
                        raise ValueError("invalid range event")
                    c = compare(self.ecosystem, version, boundary)
                    if active and (c < 0 or (event.last_affected is not None and c == 0)):
                        return True
                    active = False
            if active:
                return True
        return False


class Advisory(Contract):
    id: Id
    modified: AwareDatetime
    withdrawn: AwareDatetime | None = None
    # Attribution and original-byte digest; pack deliberately omits executable markup/details.
    source: str
    source_sha256: Sha256
    affected: list[Affected] = Field(min_length=1, max_length=100)


class Pack(Contract):
    schema_version: Literal["plumb-offline-osv-1"]
    snapshot_date: date
    publisher: Literal["GitHub Advisory Database"]
    license: Literal["CC-BY-4.0"]
    license_source: Literal["https://github.com/github/advisory-database/blob/main/LICENSE.md"]
    records: list[Advisory] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _provenance(self) -> Self:
        if len({r.id for r in self.records}) != len(self.records):
            raise ValueError("duplicate advisory ID")
        for record in self.records:
            if (
                record.modified.date() > self.snapshot_date
                or not re.fullmatch(
                    r"https://api\.osv\.dev/v1/vulns/GHSA-[a-z0-9-]+", record.source
                )
                or not record.source.endswith("/" + record.id)
            ):
                raise ValueError("invalid advisory provenance")
        return self


def load_pack(path: Path, sha256: str, *, today: date | None = None) -> Pack:
    data = bounded_bytes(path)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("advisory pack hash mismatch")
    pack = Pack.model_validate(json_data(data))
    age = ((today or datetime.now(UTC).date()) - pack.snapshot_date).days
    if age < 0 or age > MAX_AGE_DAYS:
        raise ValueError("advisory pack is stale or future-dated")
    return pack


def selected_pack(data_dir: Path) -> tuple[Pack, str]:
    # Only Plumb-owned configuration. Never target-local packs or network fallback.
    active = data_dir / "advisories" / "active.json"
    if active.exists():
        if active.is_symlink():
            raise ValueError("linked advisory selection")
        selection = json_data(bounded_bytes(active))
        sha = selection["sha256"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid advisory selection")
        path = active.parent / f"{sha}.json"
        if path.resolve().parent != active.parent.resolve() or path.is_symlink():
            raise ValueError("linked advisory pack")
        return load_pack(path, sha), sha
    pin = json_data(bounded_bytes(PIN))
    if PACK.stat().st_size != pin["size"]:
        raise ValueError("shipped advisory pack size mismatch")
    return load_pack(PACK, pin["sha256"]), pin["sha256"]


def import_pack(source: Path, sha256: str, data_dir: Path) -> Pack:
    pack = load_pack(source, sha256)
    # Re-read and verify before publishing; content addressed history is retained.
    data = bounded_bytes(source)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("pack changed during import")
    directory = data_dir / "advisories"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{sha256}.json"
    if destination.is_symlink() or (directory / "active.json").is_symlink():
        raise ValueError("linked advisory storage")
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError("existing advisory address is corrupted")
    else:
        with destination.open("xb") as handle:
            handle.write(data)
    part = directory / "active.json.part"
    if part.is_symlink():
        raise ValueError("linked advisory selection staging file")
    part.write_text(json.dumps({"sha256": sha256}) + "\n", encoding="utf-8", newline="\n")
    part.replace(directory / "active.json")
    return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import"])
    parser.add_argument("pack", type=Path)
    parser.add_argument("--sha256", required=True, help="Independently trusted pack SHA256")
    args = parser.parse_args(argv)
    try:
        pack = import_pack(args.pack, args.sha256, Settings().data_dir)
    except (OSError, ValueError, KeyError, TypeError):
        print("Advisory import refused: check hash, schema, provenance, license and freshness.")
        return 1
    print(
        f"Imported {len(pack.records)} advisory records dated {pack.snapshot_date}; offline only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

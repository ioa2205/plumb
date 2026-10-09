"""Supplementary static observations over included frozen source only."""

import ast
import hashlib
import re
import tomllib
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from analysis.advisories import Pack, compare, json_data, package_name, selected_pack
from analysis.snapshot import SnapshotStore
from analysis.syntax import span_sha256
from backend.contracts.code import ExclusionReason, ProjectSnapshot, SourceSpan
from backend.contracts.signals import SecuritySignal, SignalSet
from backend.redaction import Redactor, credential_shapes
from backend.settings import Settings

VERSION = "supplementary-signals-1"
MAX_SIGNALS = 100
MAX_PACKAGES = 10_000
BASE_LIMITATIONS = [
    "Supplementary observations are not challenged findings and do not affect coverage.",
    "Credential shapes may be placeholders; values are omitted and are not validated remotely.",
    "Configuration flags do not establish deployment exposure or exploitability.",
    "Advisory matches describe exact lockfile version exposure, not runtime exploitability.",
    "The dated advisory pack is a small curated subset, not a complete vulnerability database.",
    "Only npm package-lock/npm-shrinkwrap v2/v3 and uv.lock v1 registry packages are supported. "
    "pnpm, Yarn, requirements ranges, Git/path/workspace packages "
    "and other ecosystems are unknown.",
    "Lockfile citations cover the parsed file; no package scripts, imports or installs are run.",
]


def citation(snapshot: ProjectSnapshot, path: str, data: bytes, start: int, end: int) -> SourceSpan:
    return SourceSpan(
        snapshot_id=snapshot.id,
        path=path,
        start_line=start,
        end_line=end,
        content_sha256=span_sha256(data, start, end),
    )


def signal(
    source: SourceSpan, rule: str, category: str, summary: str, **fields: object
) -> SecuritySignal:
    address = hashlib.sha256((source.model_dump_json() + rule + repr(fields)).encode()).hexdigest()
    status = fields.pop("status", "observed")
    return SecuritySignal.model_validate(
        dict(
            id=f"signal:{address[:32]}",
            category=category,
            status=status,
            source=source,
            rule_id=rule,
            rule_version=VERSION,
            summary=summary,
            limitations=["Observation only; no challenge or runtime verification was performed."],
            **fields,
        )
    )


def configuration(text: str) -> list[tuple[str, int, int]]:
    """Direct import-bound calls only. Any alias write/shadowing conservatively refuses it."""
    tree = ast.parse(text)
    bindings: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        if isinstance(statement, ast.ImportFrom) and not statement.level:
            for alias in statement.names:
                bindings[alias.asname or alias.name] = f"{statement.module}.{alias.name}"
    shadowed = (
        {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
        | {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                shadowed.add(root.id)
    # Repeated imports can also rebind the same name. Reject even equal repeated imports.
    imported = [
        a.asname or (a.name.split(".")[0] if isinstance(n, ast.Import) else a.name)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    ]
    for name in shadowed | {n for n in imported if imported.count(n) != 1}:
        bindings.pop(name, None)
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(k.arg is None for k in node.keywords):
            continue
        call, attrs = node.func, []
        while isinstance(call, ast.Attribute):
            attrs.insert(0, call.attr)
            call = call.value
        if not isinstance(call, ast.Name) or call.id not in bindings:
            continue
        name = ".".join([bindings[call.id], *attrs])
        for keyword in node.keywords:
            if not isinstance(keyword.value, ast.Constant):
                continue
            if name == "fastapi.FastAPI" and keyword.arg == "debug" and keyword.value.value is True:
                results.append(
                    ("config-fastapi-debug", node.lineno, node.end_lineno or node.lineno)
                )
            if (
                name in {"httpx.Client", "httpx.AsyncClient"}
                and keyword.arg == "verify"
                and keyword.value.value is False
            ):
                results.append(("config-httpx-tls", node.lineno, node.end_lineno or node.lineno))
    return results


def registry_url(value: object, ecosystem: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == ("registry.npmjs.org" if ecosystem == "npm" else "pypi.org")
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
    )


def lock_packages(name: str, data: bytes) -> list[tuple[str, str, str | None]]:
    """Resolved registry package identities. Missing/ambiguous versions stay None."""
    packages = []
    if name in {"package-lock.json", "npm-shrinkwrap.json"}:
        root = json_data(data)
        if not isinstance(root, dict) or root.get("lockfileVersion") not in (2, 3):
            raise ValueError("unsupported npm lock format")
        records = root.get("packages")
        if not isinstance(records, dict) or len(records) > MAX_PACKAGES:
            raise ValueError("invalid npm packages")
        for location, record in records.items():
            if location == "":
                continue
            if not isinstance(record, dict) or not isinstance(location, str):
                raise ValueError("invalid npm record")
            if "\\" in location or any(p in {".", ".."} for p in location.split("/")):
                raise ValueError("invalid npm package location")
            if not re.fullmatch(
                r"(?:node_modules/(?:@[a-z0-9._-]+/)?[a-z0-9._-]+/)*node_modules/(?:@[a-z0-9._-]+/)?[a-z0-9._-]+",
                location,
            ):
                # Workspace records are not registry artifacts.
                continue
            installed_name = location.rsplit("node_modules/", 1)[1]
            package = package_name("npm", record.get("name", installed_name))
            version = record.get("version")
            resolved = record.get("resolved")
            known = registry_url(resolved, "npm") and record.get("link") is not True
            if known:
                # Aliases must name the registry package; tarball identity must agree.
                prefix = unquote(urlsplit(resolved).path).split("/-/", 1)[0].lstrip("/")
                known = prefix == package
            try:
                if not isinstance(version, str) or not known:
                    raise ValueError("unresolved package version")
                compare("npm", version, version)
            except ValueError:
                version = None
            packages.append(("npm", package, version))
    elif name == "uv.lock":
        root = tomllib.loads(data.decode("utf-8"))
        if root.get("version") != 1 or not isinstance(root.get("package"), list):
            raise ValueError("unsupported uv lock format")
        records = root["package"]
        if len(records) > MAX_PACKAGES:
            raise ValueError("uv package limit")
        for record in records:
            package = package_name("PyPI", record["name"])
            version = record.get("version")
            source = record.get("source", {})
            known = (
                isinstance(source, dict)
                and set(source) == {"registry"}
                and registry_url(source["registry"], "PyPI")
            )
            try:
                if not isinstance(version, str) or not known or len(version) > 100:
                    raise ValueError("unresolved package version")
                compare("PyPI", version, version)
            except ValueError:
                version = None
            packages.append(("PyPI", package, version))
    else:
        raise ValueError("unsupported lockfile")
    return list(dict.fromkeys(packages))


def dependency_signals(
    source: SourceSpan, packages: list[tuple[str, str, str | None]], pack: Pack
) -> list[SecuritySignal]:
    results = []
    for ecosystem, name, version in packages:
        if version is None:
            results.append(
                signal(
                    source,
                    "dependency-version-unknown",
                    "dependency",
                    "Registry identity or exact resolved version is unknown; "
                    "advisories were not matched.",
                    ecosystem=ecosystem,
                    package=name,
                    status="unknown",
                )
            )
            continue
        for record in pack.records:
            if record.withdrawn is not None:
                continue
            if any(
                a.ecosystem == ecosystem
                and package_name(ecosystem, a.name) == name
                and a.contains(version)
                for a in record.affected
            ):
                results.append(
                    signal(
                        source,
                        record.id,
                        "dependency",
                        "Exact resolved version matches a dated offline advisory; exposure only.",
                        ecosystem=ecosystem,
                        package=name,
                        version=version,
                        advisory_id=record.id,
                    )
                )
            if len(results) > MAX_SIGNALS:
                return results
    return results


def observe(
    snapshot: ProjectSnapshot, store: SnapshotStore, settings: Settings, run_id: str
) -> SignalSet:
    signals: list[SecuritySignal] = []
    limits = [*BASE_LIMITATIONS]
    partial = False
    pack, sha = None, None
    try:
        pack, sha = selected_pack(settings.data_dir)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        partial = True
        limits.append(
            "Advisory pack unavailable, malformed, modified, stale or future-dated; "
            "dependency checks were not run."
        )
    excluded = sum(item.reason == ExclusionReason.SECRET for item in snapshot.excluded)
    limits.append(
        f"{excluded} known secret files were excluded from the snapshot and were not opened."
    )
    for file in snapshot.files:
        data = store.read(snapshot, file.path)
        text = data.decode("utf-8", errors="replace")
        for shape in credential_shapes(text, snapshot.id):
            start = text.count("\n", 0, shape.start) + 1
            end = text.count("\n", 0, max(shape.start, shape.end - 1)) + 1
            signals.append(
                signal(
                    citation(snapshot, file.path, data, start, end),
                    "secret-" + shape.rule,
                    "secret",
                    "Credential-shaped text detected: [REDACTED].",
                    fingerprint=shape.fingerprint,
                )
            )
        if file.path.endswith(".py"):
            try:
                for rule, start, end in configuration(text):
                    signals.append(
                        signal(
                            citation(snapshot, file.path, data, start, end),
                            rule,
                            "configuration",
                            "Literal FastAPI debug mode is enabled."
                            if rule == "config-fastapi-debug"
                            else "Literal HTTPX TLS certificate verification is disabled.",
                        )
                    )
            except (SyntaxError, RecursionError, ValueError):
                partial = True
                limits.append(
                    "Some Python configuration syntax was unparseable; no flag was inferred."
                )
        name = PurePosixPath(file.path).name
        if name in {"package-lock.json", "npm-shrinkwrap.json", "uv.lock"}:
            try:
                packages = lock_packages(name, data)
                if pack is not None:
                    lines = max(1, len(data.splitlines()))
                    signals.extend(
                        dependency_signals(
                            citation(snapshot, file.path, data, 1, lines), packages, pack
                        )
                    )
            except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                partial = True
                limits.append(
                    "A supported lockfile was malformed or exceeded parser bounds; "
                    "its dependency exposure is unknown."
                )
        elif name in {"pnpm-lock.yaml", "yarn.lock", "Pipfile.lock", "poetry.lock"}:
            partial = True
            limits.append(
                "Included unsupported lockfiles were not advisory-matched; "
                "dependency scope remains incomplete."
            )
        if len(signals) > MAX_SIGNALS:
            partial = True
            signals = signals[:MAX_SIGNALS]
            limits.append(
                "Signal limit reached (100); remaining included files/signals "
                "were not fully checked."
            )
            break
    result = SignalSet(
        run_id=run_id,
        snapshot_id=snapshot.id,
        tool_version=VERSION,
        status="partial" if partial else "ok",
        signals=signals,
        pack_sha256=sha,
        pack_date=pack.snapshot_date if pack else None,
        pack_source=pack.publisher if pack else None,
        limitations=list(dict.fromkeys(limits)),
    )
    return SignalSet.model_validate(
        Redactor.configured(settings).strings(result.model_dump(mode="json"))
    )

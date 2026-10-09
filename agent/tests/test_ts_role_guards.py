"""Helper behavior, receiver binding and actual denial must all exist in source."""

import re
from pathlib import Path

import pytest

from agent.boundaries import BoundaryInvestigator, finding
from agent.guard_syntax import Check, _sql_executors, checks
from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.validator import Unconfirmed
from analysis.index import Index, index_path
from analysis.nextjs import NextEntry, NextJSMap
from analysis.resolution import CallGraph
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.code import EntryPoint, EntryPointKind
from backend.contracts.common import Framework, Language, LinkStatus
from backend.contracts.investigation import Conclusion

from .test_guards import Stub, spend

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "labs/tandir/web/app/api/admin/reports/route.ts").read_bytes()
HELPER = (ROOT / "labs/tandir/web/lib/sessions.ts").read_bytes()
CONFIG = (ROOT / "labs/tandir/web/tsconfig.json").read_bytes()
DATABASE = (ROOT / "labs/tandir/web/lib/db.ts").read_bytes()
PATH = "web/app/api/admin/reports/route.ts"


@pytest.mark.parametrize("mode", ["exact", "alias", "missing", "ambiguous", "escape", "fake"])
def test_sql_executor_uses_exact_frozen_json_alias_and_body(mode: str) -> None:
    route = ROUTE
    files = {"web/tsconfig.json": CONFIG, "web/lib/db.ts": DATABASE}
    if mode == "alias":
        route = route.replace(b"{ all }", b"{ all as rows }").replace(b"= all<", b"= rows<")
    elif mode == "missing":
        files.pop("web/tsconfig.json")
    elif mode == "ambiguous":
        files["web/lib/db/index.ts"] = DATABASE
    elif mode == "escape":
        files["web/tsconfig.json"] = b'{"compilerOptions":{"paths":{"@/*":["../../../*"]}}}'
    elif mode == "fake":
        files["web/lib/db.ts"] = DATABASE.replace(
            b"return db().prepare(sql).all(...params)", b"return fabricated(sql, params)"
        )
    assert _sql_executors(route, Language.TYPESCRIPT, PATH, files.get) == (
        {"rows" if mode == "alias" else "all"} if mode in {"exact", "alias"} else set()
    )


def facts(route: bytes = ROUTE, helper: bytes = HELPER, config: bytes = CONFIG) -> list[Check]:
    files = {"web/lib/sessions.ts": helper, "web/tsconfig.json": config}
    return checks(Language.TYPESCRIPT, route, 1, len(route.splitlines()), path=PATH, read=files.get)


def test_actual_reports_guard_has_factory_and_predicate_evidence() -> None:
    found = facts()
    assert len(found) == 1
    assert found[0].roles == ("admin",)
    assert (found[0].start, found[0].focus, found[0].end) == (7, 9, 9)
    assert [c.label for c in found[0].context] == ["role predicate", "receiver factory"]
    assert b"return roles.includes(this.role)" in found[0].context[0].source


@pytest.mark.parametrize(
    "old,new",
    [
        (b'!viewer.is("admin")', b'viewer.is("admin")'),
        (b'!viewer.is("admin")', b'!viewer.is("admin") && enabled'),
        (b'!viewer.is("admin")', b"!viewer.is(requiredRole)"),
        (b'!viewer.is("admin")', b'!viewer.other("admin")'),
        (b"{ status: 403 }", b"{ status: 200 }"),
        (
            b'return Response.json({ detail: "Not allowed" }, { status: 403 })',
            b'log("Not allowed")',
        ),
        (b"  if (!viewer.is", b"  disclose();\n  if (!viewer.is"),
        (b"  if (!viewer.is", b"  if (enabled) return Response.json(data);\n  if (!viewer.is"),
        (b"  if (!viewer.is", b"  if (enabled) { if (!viewer.is"),
        (b"const viewer =", b"let viewer ="),
        (b"const viewer = viewerForToken", b"const viewer = unrelated"),
        (b"GET(request: NextRequest)", b"GET(request: NextRequest, viewerForToken: Function)"),
        (b"GET(request: NextRequest)", b"GET(request: NextRequest, Response: any)"),
        (b"  const rows =", b"  viewer.is = () => true;\n  const rows ="),
        (b"import type", b"const Response = fake;\nimport type"),
    ],
)
def test_unsupported_or_non_enforcing_call_never_confirms(old: bytes, new: bytes) -> None:
    assert not facts(ROUTE.replace(old, new))


@pytest.mark.parametrize(
    "old,new",
    [
        (b"return roles.includes(this.role)", b"return true"),
        (b"return roles.includes(this.role)", b'return roles.includes("admin")'),
        (b"return roles.includes(this.role)", b"return !roles.includes(this.role)"),
        (
            b"return roles.includes(this.role)",
            b"// return roles.includes(this.role)\n    return false",
        ),
        (b"readonly role:", b"role:"),
        (b") {}", b') { this.role = "admin"; }'),
        (b"new Viewer(row.id, row.role, row.branch_id, row.display_name)", b"fakeViewer"),
        (b"export function viewerForToken", b"function viewerForToken"),
        (b"export class Viewer {", b"export class Viewer extends Other {"),
        (b"export class Viewer {", b"Viewer.prototype.is = () => true;\nexport class Viewer {"),
    ],
)
def test_helper_name_or_signature_does_not_prove_its_behavior(old: bytes, new: bytes) -> None:
    assert not facts(helper=HELPER.replace(old, new))


@pytest.mark.parametrize(
    "config",
    [
        b"{}",
        b"{broken",
        b'{"extends":"../tsconfig.json"}',
        b'{"compilerOptions":{"paths":{"@/*":["../../../*"]}}}',
    ],
)
def test_unknown_or_escaping_alias_is_not_guessed(config: bytes) -> None:
    assert not facts(config=config)


def test_relative_import_alias_and_braced_denial() -> None:
    route = (
        ROUTE.replace(b"viewerForToken }", b"viewerForToken as fromToken }")
        .replace(b"= viewerForToken(", b"= fromToken(")
        .replace(b"@/lib/sessions", b"../../../../lib/sessions")
    )
    route = route.replace(
        b'if (!viewer.is("admin")) return', b'if (!viewer.is("admin")) { return'
    ).replace(b"{ status: 403 });", b"{ status: 403 }); }")
    assert len(facts(route)) == 1


def test_classification_validator_and_cache_bind_the_helper_snapshot(tmp_path: Path) -> None:
    project = tmp_path / "project"
    for path, data in {
        PATH: ROUTE,
        "web/lib/sessions.ts": HELPER,
        "web/tsconfig.json": CONFIG,
    }.items():
        file = project / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    store = SnapshotStore(tmp_path / "store")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(tmp_path, snapshot.id))
    try:
        symbol = next(
            index.to_contract(r, snapshot.id)
            for r in index.symbols()
            if r.path == PATH and r.name == "GET"
        )
    finally:
        index.close()
    model = Stub("role", None, None, "L3")
    classifier = Classifier(
        snapshot, store, model, SummaryCache(tmp_path / "cache.sqlite"), identity="test"
    )
    summary = classifier.classify(symbol, spend())
    assert not summary.issues and summary.guards[0].canonical == "ROLE(admin)"
    assert "roles.includes(this.role)" in model.calls[0].user
    assert "new Viewer(row.id, row.role" in model.calls[0].user
    assert classifier.classify(symbol, spend()) == summary
    assert classifier.cache_hits == 1
    # Same callsite, changed helper bytes: no stale summary or forged confirmation.
    (project / "web/lib/sessions.ts").write_bytes(
        HELPER.replace(b"return roles.includes(this.role)", b"return true")
    )
    changed = take_snapshot(project, store)
    changed_classifier = Classifier(changed, store, model, classifier.cache, identity="test")
    changed_symbol = symbol.model_copy(
        update={
            "snapshot_id": changed.id,
            "span": symbol.span.model_copy(update={"snapshot_id": changed.id}),
        }
    )
    assert not changed_classifier.classify(changed_symbol, spend()).guards
    forged = summary.guards[0].model_copy(
        update={
            "snapshot_id": changed.id,
            "span": summary.guards[0].span.model_copy(update={"snapshot_id": changed.id}),
        }
    )
    with pytest.raises(Unconfirmed):
        changed_classifier.validator.confirm(forged)


@pytest.mark.parametrize("protected", [True, False])
def test_challenge_and_export_keep_actual_helper_proof(tmp_path: Path, protected: bool) -> None:
    project = tmp_path / "project"
    route = (
        ROUTE
        if protected
        else ROUTE.replace(b'if (!viewer.is("admin"))', b'if (viewer.is("admin"))')
    )
    for path, data in {
        PATH: route,
        "web/lib/sessions.ts": HELPER,
        "web/tsconfig.json": CONFIG,
    }.items():
        file = project / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    store = SnapshotStore(tmp_path / "store")
    snapshot = take_snapshot(project, store)
    index = Index.build(snapshot, store, index_path(tmp_path, snapshot.id))

    class Model(Stub):
        def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
            self.calls.append(request)
            if request.name == "guard_summary":
                focus = re.search(r"Classify ONLY the check or query on (L\d+)", request.user)
                assert focus is not None
                assert "roles.includes(this.role)" in request.user
                return JsonAnswer(
                    {
                        "guards": [
                            {
                                "kind": "role",
                                "subject": None,
                                "object": None,
                                "line_ids": [focus[1]],
                            }
                        ]
                    },
                    "",
                    1,
                    1,
                    0,
                )
            return JsonAnswer({"reason": "none_found", "line_ids": []}, "", 1, 1, 0)

    try:
        symbol = next(
            index.to_contract(r, snapshot.id)
            for r in index.symbols()
            if r.path == PATH and r.name == "GET"
        )
        entry = EntryPoint(
            id="entry:reports",
            snapshot_id=snapshot.id,
            kind=EntryPointKind.ROUTE_HANDLER,
            framework=Framework.NEXTJS,
            handler_symbol_id=symbol.id,
            span=symbol.span,
        )
        nextjs = NextJSMap(
            snapshot_id=snapshot.id,
            entries=[NextEntry(entry=entry, project="web", status=LinkStatus.RESOLVED, proxies=[])],
            components=[],
            client_props=[],
            data_modules=[],
            proxies=[],
            issues=[],
        )
        # Missing method edges must not remove the source proof from the questions.
        graph = CallGraph(
            snapshot_id=snapshot.id, language="typescript", resolver_version="fixture", edges=[]
        )
        model = Model()
        classifier = Classifier(
            snapshot, store, model, SummaryCache(tmp_path / "guards.sqlite"), identity="fixture"
        )
        boundary = BoundaryInvestigator(snapshot, store, index, graph, nextjs, classifier)
        result = boundary.investigate(entry.id, model, spend())
        assert result.conclusion == (Conclusion.REJECTED if protected else Conclusion.INCONCLUSIVE)
        assert len(result.samples) == 3
        report = finding(result, boundary, run_id="run:test", display_id="F-01")
        assert not classifier.validator.finding(report, guards=result.guards)
        if protected:
            assert len(model.calls) == 4
            assert any(
                e.span.path == "web/lib/sessions.ts" and e.span.start_line == 14
                for e in report.exhibits
            )
    finally:
        index.close()

"""Executable guard validation and cache boundaries, independent of model judgment."""

import hashlib
import re
import sqlite3
from pathlib import Path

import pytest

from agent.guard_syntax import Check, checks
from agent.guards import Classifier, Summary, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import GuardKind, GuardMechanism, SourceSpan, Symbol, SymbolKind
from backend.contracts.common import Language
from backend.contracts.investigation import Budget

OWNER = b"""from fastapi import HTTPException
def check(order, user):
    if order.customer_id != user.id:
        raise HTTPException(status_code=404)
    return order
"""
AUTH = b"""from fastapi import HTTPException
def check(user):
    if user is None:
        raise HTTPException(status_code=401)
    return user
"""
MIXED = b"""from fastapi import HTTPException
def check(order: Order, user: User):
    if user is None:
        raise HTTPException(status_code=401)
    if order.customer_id != user.id:
        raise HTTPException(status_code=404)
    if user.role not in ('admin',):
        raise HTTPException(status_code=403)
    return order
"""


def test_cache_only_scheduling_never_asks_model_or_treats_a_miss_as_absence(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    classifier.cached_only = True
    missing = classifier.classify(symbol, Spend(Budget()), resource="Order")
    assert not model.calls and not missing.guards and missing.issues
    classifier.cached_only = False
    fresh = classifier.classify(symbol, Spend(Budget()), resource="Order")
    assert fresh.guards and not fresh.issues
    calls = len(model.calls)
    classifier.cached_only = True
    cached = classifier.classify(symbol, Spend(Budget()), resource="Order")
    assert cached == fresh and len(model.calls) == calls and classifier.cache_hits == 1
    classifier.identity = "different profile"
    changed = classifier.classify(symbol, Spend(Budget()), resource="Order")
    assert changed.issues and not changed.guards and len(model.calls) == calls


SQL = b"""import { one } from "./db";
export function check(viewer, id) {
  const order = one("SELECT * FROM orders WHERE id = ? AND customer_id = ?", id, viewer.id);
  return order;
}
"""
DB = b"""import { DatabaseSync } from "node:sqlite";
const connection = {db: new DatabaseSync(":memory:")};
export function db() { return connection.db; }
export function one<T>(sql: string, ...params: unknown[]): T {
  return db().prepare(sql).get(...params) as T;
}
"""


class Stub:
    def __init__(
        self,
        kind: str = "owner",
        subject: str | None = "user.id",
        object: str | None = "order.customer_id",
        citation: str = "L1",
    ) -> None:
        self.kind, self.subject, self.object, self.citation = kind, subject, object, citation
        self.calls: list[ModelRequest] = []

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.calls.append(request)
        return JsonAnswer(
            {
                "guards": [
                    {
                        "kind": self.kind,
                        "subject": self.subject,
                        "object": self.object,
                        "line_ids": [self.citation],
                    }
                ]
            },
            "",
            1,
            1,
            0,
        )


class ConstructJudge(Stub):
    """Fixture answers selected by the packet, never an accuracy measurement."""

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.calls.append(request)
        props = request.schema["properties"]["guards"]["items"]["properties"]
        kind = next(
            k for k in ("authenticated", "role", "owner", "unknown") if k in props["kind"]["enum"]
        )
        focus = re.search(r"Classify ONLY the check or query on (L\d+)", request.user)
        assert focus
        return JsonAnswer(
            {
                "guards": [
                    {
                        "kind": kind,
                        "subject": next(
                            (v for v in props["subject"].get("enum", []) if v is not None), None
                        ),
                        "object": next(
                            (v for v in props["object"].get("enum", []) if v is not None), None
                        ),
                        "line_ids": [focus[1]],
                    }
                ]
            },
            "",
            1,
            1,
            0,
        )


def setup(
    root: Path, model: Stub, source: bytes = OWNER, language: Language = Language.PYTHON
) -> tuple[Classifier, Symbol]:
    project = root / "project"
    project.mkdir(exist_ok=True)
    path = "guard.py" if language is Language.PYTHON else "guard.ts"
    (project / path).write_bytes(source)
    if language is Language.TYPESCRIPT:
        (project / "db.ts").write_bytes(DB)
    store = SnapshotStore(root / "store")
    snapshot = take_snapshot(project, store)
    lines = len(source.splitlines())
    symbol = Symbol(
        id="symbol:check",
        snapshot_id=snapshot.id,
        name="check",
        qualified_name="check",
        kind=SymbolKind.FUNCTION,
        language=language,
        span=SourceSpan(
            snapshot_id=snapshot.id,
            path=path,
            start_line=2,
            end_line=lines,
            content_sha256=span_sha256(source, 2, lines),
        ),
    )
    return Classifier(
        snapshot, store, model, SummaryCache(root / "summaries.sqlite"), identity="pin:v1"
    ), symbol


def spend() -> Spend:
    return Spend(Budget())


def test_cache_closes_connections_and_commits_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def tracked_connect(path: Path) -> sqlite3.Connection:
        connection = connect(path)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    cache = SummaryCache(tmp_path / "owned.sqlite")
    (tmp_path / "source").mkdir()
    _, symbol = setup(tmp_path / "source", Stub())
    summary = Summary(
        symbol_id=symbol.id, snapshot_id=symbol.snapshot_id, span=symbol.span, guards=[]
    )
    assert cache.get("missing") is None
    cache.put("saved", summary)
    assert cache.get("saved") == summary
    # Check closure without relying on GC timing or Windows file-lock semantics.
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    cache.path.unlink()


def test_cache_closes_connection_on_sql_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = SummaryCache(tmp_path / "owned.sqlite")
    connection = sqlite3.connect(cache.path)
    connection.execute("DROP TABLE summaries")
    connection.commit()
    monkeypatch.setattr(sqlite3, "connect", lambda path: connection)
    with pytest.raises(sqlite3.OperationalError):
        cache.get("missing")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_recognizer_identity_change_cannot_reuse_cached_judgments(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    first = classifier.classify(symbol, spend(), resource="Order")
    assert first.guards and len(model.calls) == 1
    classifier.recognizer_sha256 = "a" * 64
    assert classifier.classify(symbol, spend(), resource="Order").guards
    assert len(model.calls) == 2


def test_owner_canonical_and_cached_reuse(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    summary = classifier.classify(symbol, spend(), resource="Order")
    assert summary.issues == []
    assert summary.guards[0].canonical == "OWNER(Order.customer_id = principal.id)"
    assert summary.guards[0].confirmed
    assert classifier.validator.evidence(summary.guards[0].span) == []
    assert classifier.classify(symbol, spend(), resource="Order") == summary
    assert len(model.calls) == classifier.cache_hits == 1


@pytest.mark.parametrize(
    "kind,source,subject,object,canonical",
    [
        ("authenticated", AUTH, None, None, "AUTHN"),
        (
            "tenant",
            OWNER.replace(b"customer_id", b"branch_id").replace(b"user.id", b"user.branch_id"),
            "user.branch_id",
            "order.branch_id",
            "TENANT(Order.branch_id = principal.branch_id)",
        ),
        ("owner", SQL, "viewer.id", "customer_id", "OWNER(Order.customer_id = principal.id)"),
    ],
)
def test_executable_forms(
    tmp_path: Path,
    kind: str,
    source: bytes,
    subject: str | None,
    object: str | None,
    canonical: str,
) -> None:
    language = Language.TYPESCRIPT if source == SQL else Language.PYTHON
    classifier, symbol = setup(tmp_path, Stub(kind, subject, object), source, language)
    summary = classifier.classify(symbol, spend(), resource="Order")
    assert not summary.issues
    assert summary.guards[0].canonical == canonical


@pytest.mark.parametrize(
    "subject,object,citation",
    [
        ("admin_user.id", "order.customer_id", "L1"),
        ("user.id", "order.identity", "L1"),
        ("user.id", "order.customer_id", "L999"),
        (None, None, "L1"),
        ("user.id", "order.customer_id", "L2"),
    ],
)
def test_invalid_answer_is_not_confirmed_or_cached(
    tmp_path: Path, subject: str | None, object: str | None, citation: str
) -> None:
    model = Stub(subject=subject, object=object, citation=citation)
    classifier, symbol = setup(tmp_path, model)
    summary = classifier.classify(symbol, spend())
    assert not summary.guards and summary.issues
    classifier.classify(symbol, spend())
    assert len(model.calls) == 2 and classifier.cache_hits == 0


@pytest.mark.parametrize(
    "source",
    [
        b"def check(order, user):\n    # Require order.customer_id == user.id\n    return order\n",
        b"def require_owner(order, user):\n    return order\n",
        OWNER.replace(b"raise HTTPException(status_code=404)", b"print('denied')"),
        OWNER.replace(b"!=", b"=="),
        OWNER.replace(b"    if order.customer_id", b"    return order\n    if order.customer_id"),
        OWNER.replace(
            b"    if order.customer_id", b"    if enabled:\n        if order.customer_id"
        ).replace(b"        raise", b"            raise"),
        OWNER.replace(b"order.customer_id != user.id", b"order.customer_id != user.id and enabled"),
        OWNER.replace(
            b"    if order.customer_id", b"    if enabled: return order\n    if order.customer_id"
        ),
        OWNER.replace(
            b"    if order.customer_id", b"    disclose(order)\n    if order.customer_id"
        ),
        OWNER.replace(
            b"    if order.customer_id", b"    order.status = 'done'\n    if order.customer_id"
        ),
    ],
)
def test_non_enforced_comparison_and_misleading_names_never_confirm(
    tmp_path: Path,
    source: bytes,
) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model, source)
    assert classifier.classify(symbol, spend()).guards == []
    assert not model.calls


@pytest.mark.parametrize(
    "sql",
    [
        SQL.replace(b"AND", b"OR"),
        SQL.replace(b"customer_id = ?", b"customer_id != ?"),
        SQL.replace(b"customer_id = ?", b"customer_id = ${viewer.id}"),
        SQL.replace(b", id, viewer.id", b", viewer.id, id"),
        SQL.replace(b"SELECT *", b"SELECT * /* trusted */"),
    ],
)
def test_sql_binding_and_boolean_failures_are_not_owner_guards(sql: bytes) -> None:
    facts = checks(
        Language.TYPESCRIPT,
        sql,
        1,
        len(sql.splitlines()),
        path="guard.ts",
        read=lambda path: DB if path == "db.ts" else None,
    )
    assert not any(("customer_id", "viewer.id") in fact.pairs for fact in facts)


def test_sql_helper_name_and_query_string_alone_are_not_execution() -> None:
    for source in (None, DB.replace(b"db().prepare(sql).get(...params) as T", b"{} as T")):
        assert (
            checks(
                Language.TYPESCRIPT,
                SQL,
                1,
                5,
                path="guard.ts",
                read=lambda path, source=source: source,
            )
            == []
        )


def test_query_predicate_not_executed_is_not_a_guard() -> None:
    source = (
        b"def check(db,user):\n"
        b"    q=select(Order).where(Order.customer_id == user.id)\n"
        b"    return db.get(Order,1)\n"
    )
    assert checks(Language.PYTHON, source, 1, 3) == []


def test_cache_tampering_is_revalidated(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    summary = classifier.classify(symbol, spend())
    with sqlite3.connect(classifier.cache.path) as db:
        key = db.execute("SELECT key FROM summaries").fetchone()[0]
    data = summary.model_dump()
    data["guards"][0]["span"]["content_sha256"] = "0" * 64
    classifier.cache.put(key, type(summary).model_validate(data))
    assert classifier.classify(symbol, spend()) == summary
    assert len(model.calls) == 2 and classifier.cache_hits == 0


def test_model_identity_and_source_change_invalidate_cache(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    classifier.classify(symbol, spend())
    classifier.identity = "pin:v2"
    classifier.classify(symbol, spend())
    assert len(model.calls) == 2
    second, changed = setup(tmp_path, model, OWNER + b"# changed\n")
    second.classify(changed, spend())
    assert len(model.calls) == 3


def test_orientation_comes_from_resource_binding_not_model_field_order(tmp_path: Path) -> None:
    source = OWNER.replace(b"order, user", b"order: Order, user: User")
    model = Stub()
    classifier, symbol = setup(tmp_path, model, source)
    classifier.classify(symbol, spend(), resource="Order")
    fields = model.calls[0].schema["properties"]["guards"]["items"]["properties"]
    assert fields["subject"]["enum"] == [None, "user.id"]
    assert fields["object"]["enum"] == [None, "order.customer_id"]


def test_cross_snapshot_and_stale_spans_refuse_before_inference(tmp_path: Path) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    with pytest.raises(ValueError):
        classifier.classify(
            symbol.model_copy(update={"snapshot_id": hashlib.sha256(b"other").hexdigest()}), spend()
        )
    stale = symbol.model_copy(
        update={"span": symbol.span.model_copy(update={"content_sha256": "0" * 64})}
    )
    with pytest.raises(ValueError):
        classifier.classify(stale, spend())
    assert model.calls == []


@pytest.mark.parametrize("required", [GuardKind.AUTHENTICATED, GuardKind.OWNER, GuardKind.ROLE])
def test_scoped_classification_selects_constructs_and_preserves_default(
    tmp_path: Path, required: GuardKind
) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    scoped = classifier.classify(symbol, spend(), resource="Order", required_kind=required)
    assert not scoped.issues and [g.kind for g in scoped.guards] == [required]
    assert len(model.calls) == 1
    assert classifier.classify(symbol, spend(), resource="Order", required_kind=required) == scoped
    assert classifier.cache_hits == 1 and len(model.calls) == 1
    complete = classifier.classify(symbol, spend(), resource="Order")
    assert not complete.issues
    assert {g.kind for g in complete.guards} == {
        GuardKind.AUTHENTICATED,
        GuardKind.OWNER,
        GuardKind.ROLE,
    }
    assert len(model.calls) == 4


def test_owner_and_tenant_ambiguity_is_not_decided_by_the_requirement(tmp_path: Path) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    for required in (GuardKind.OWNER, GuardKind.TENANT):
        result = classifier.classify(symbol, spend(), resource="Order", required_kind=required)
        assert not result.issues and result.guards[0].kind is GuardKind.OWNER
        kinds = model.calls[-1].schema["properties"]["guards"]["items"]["properties"]["kind"][
            "enum"
        ]
        assert "owner" in kinds and "tenant" in kinds
    assert len(model.calls) == 2 and classifier.cache_hits == 0


@pytest.mark.parametrize("citation", ["L2", "L999"])
def test_required_check_citation_failure_is_never_filtered_or_cached(
    tmp_path: Path, citation: str
) -> None:
    model = Stub("authenticated", None, None, citation)
    classifier, symbol = setup(tmp_path, model, MIXED)
    for _ in range(2):
        result = classifier.classify(symbol, spend(), required_kind=GuardKind.AUTHENTICATED)
        assert result.issues and not result.guards
    assert len(model.calls) == 2 and classifier.cache_hits == 0


def test_unknown_candidate_remains_an_issue_in_scoped_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    recognized = checks(symbol.language, MIXED, symbol.span.start_line, symbol.span.end_line)
    uncertain = Check(9, 9, 9, GuardMechanism.COMPARISON)
    monkeypatch.setattr("agent.guards.checks", lambda *args, **kwargs: [*recognized, uncertain])
    result = classifier.classify(symbol, spend(), required_kind=GuardKind.AUTHENTICATED)
    assert [g.kind for g in result.guards] == [GuardKind.AUTHENTICATED]
    assert result.issues and "unrecognized" in " ".join(result.issues)
    assert len(model.calls) == 2
    with sqlite3.connect(classifier.cache.path) as db:
        assert db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0


def test_scoped_cache_rejects_a_summary_with_unrelated_guards(tmp_path: Path) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    scoped = classifier.classify(
        symbol, spend(), resource="Order", required_kind=GuardKind.AUTHENTICATED
    )
    with sqlite3.connect(classifier.cache.path) as db:
        key = db.execute("SELECT key FROM summaries").fetchone()[0]
    complete = classifier.classify(symbol, spend(), resource="Order")
    classifier.cache.put(key, complete)
    assert (
        classifier.classify(
            symbol, spend(), resource="Order", required_kind=GuardKind.AUTHENTICATED
        )
        == scoped
    )
    assert len(model.calls) == 5 and classifier.cache_hits == 0


def test_scoped_cache_miss_cannot_use_an_unscoped_summary_or_old_identity(tmp_path: Path) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    classifier.classify(symbol, spend(), resource="Order")
    classifier.cached_only = True
    assert classifier.classify(
        symbol, spend(), resource="Order", required_kind=GuardKind.AUTHENTICATED
    ).issues
    classifier.cached_only = False
    classifier.classify(symbol, spend(), resource="Order", required_kind=GuardKind.AUTHENTICATED)
    classifier.cached_only = True
    classifier.recognizer_sha256 = "b" * 64
    assert classifier.classify(
        symbol, spend(), resource="Order", required_kind=GuardKind.AUTHENTICATED
    ).issues
    assert len(model.calls) == 4 and classifier.cache_hits == 0


@pytest.mark.parametrize("required", [GuardKind.NONE, GuardKind.UNKNOWN, GuardKind.MINIMIZED])
def test_invalid_classification_scope_refuses_before_inference(
    tmp_path: Path, required: GuardKind
) -> None:
    model = Stub()
    classifier, symbol = setup(tmp_path, model)
    with pytest.raises(ValueError, match="authorization guard kind"):
        classifier.classify(symbol, spend(), required_kind=required)
    assert not model.calls


@pytest.mark.parametrize("changed", ["snapshot", "span", "language"])
def test_scoped_classification_still_validates_the_exact_source(
    tmp_path: Path, changed: str
) -> None:
    model = ConstructJudge()
    classifier, symbol = setup(tmp_path, model, MIXED)
    if changed == "snapshot":
        symbol = symbol.model_copy(update={"snapshot_id": "a" * 64})
    elif changed == "span":
        symbol = symbol.model_copy(
            update={"span": symbol.span.model_copy(update={"content_sha256": "a" * 64})}
        )
    else:
        symbol = symbol.model_copy(update={"language": Language.TYPESCRIPT})
    with pytest.raises(ValueError):
        classifier.classify(symbol, spend(), required_kind=GuardKind.AUTHENTICATED)
    assert not model.calls

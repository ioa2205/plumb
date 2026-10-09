"""Source-bound peer leads, not verdicts (PROJECT_PLAN §3.2).

All included sites stay in the denominator unless a cited code-level exception
is established. Unsupported paths remain visible. No target code is executed.
"""

import ast
import hashlib
from collections import defaultdict

from pydantic import Field

from agent.guard_syntax import checks
from agent.guards import Classifier, Summary
from agent.llm import Spend
from analysis.access import REQUEST_ORIGINS, AccessMap, AccessPath
from analysis.fastapi import Dependency, FastAPIMap, FastAPIRoute, extract_fastapi
from analysis.index import Index
from analysis.python_syntax import dotted
from analysis.resolution import CallEdge, CallGraph, LinkStatus
from analysis.syntax import span_sha256
from backend.contracts.code import (
    Guard,
    GuardKind,
    GuardMechanism,
    PeerColumn,
    PeerDeviation,
    PeerExclusion,
    PeerGroup,
    SourceSpan,
    Symbol,
)
from backend.contracts.common import Contract, InputOrigin, Language
from backend.contracts.investigation import Budget
from backend.settings import Settings


class SiteChecks(Contract):
    site_id: str
    guards: list[Guard] = Field(default_factory=list)
    evidence: list[SourceSpan] = Field(default_factory=list)
    exclusion: str | None = None
    issues: list[str] = Field(default_factory=list)


class PeerResult(Contract):
    snapshot_id: str
    groups: list[PeerGroup]
    checks: list[SiteChecks]
    limitations: list[str]


def consensus(access: AccessMap, checks: list[SiteChecks], settings: Settings) -> list[PeerGroup]:
    """Distinct sites vote once; the subject itself never votes as its own peer."""
    sites = {a.site.id: a.site for a in access.accesses}
    if len(sites) != len(access.accesses):
        raise ValueError("duplicate access identities")
    facts = {item.site_id: item for item in checks}
    if len(facts) != len(checks) or set(facts) != set(sites):
        raise ValueError("each included access must have exactly one check record")
    by_resource: dict[str, list[str]] = defaultdict(list)
    for site in sites.values():
        if site.snapshot_id != access.snapshot_id:
            raise ValueError("peer sites must use the same snapshot")
        by_resource[site.resource].append(site.id)
        fact = facts[site.id]
        if fact.exclusion and not fact.evidence:
            raise ValueError("exclusion needs code evidence")
        for guard in fact.guards:
            if not guard.confirmed or guard.snapshot_id != access.snapshot_id or guard.optimistic:
                raise ValueError("only confirmed non-optimistic snapshot guards may vote")
    groups = []
    for resource, identifiers in sorted(by_resource.items()):
        identifiers.sort()
        voters = [i for i in identifiers if facts[i].exclusion is None]
        columns = []
        deviations = []
        for kind in (GuardKind.AUTHENTICATED, GuardKind.OWNER, GuardKind.TENANT, GuardKind.ROLE):
            applying = [i for i in voters if any(g.kind is kind for g in facts[i].guards)]
            if not applying:
                continue
            columns.append(PeerColumn(key=kind.value, label=kind.value, applied_site_ids=applying))
            for identifier in voters:
                if identifier in applying:
                    continue
                total = len(voters) - 1
                if (
                    total > 0
                    and len(applying) >= settings.peer_min_peers
                    and len(applying) / total >= settings.peer_min_share
                ):
                    deviations.append(
                        PeerDeviation(
                            site_id=identifier,
                            missing=kind.value,
                            peers_applying=len(applying),
                            peers_total=total,
                        )
                    )
        groups.append(
            PeerGroup(
                id="peers:"
                + hashlib.sha256(f"{access.snapshot_id}:{resource}".encode()).hexdigest()[:24],
                snapshot_id=access.snapshot_id,
                resource=resource,
                site_ids=identifiers,
                columns=columns,
                excluded=[
                    PeerExclusion(site_id=i, reason=facts[i].exclusion or "")
                    for i in identifiers
                    if facts[i].exclusion
                ],
                min_peers=settings.peer_min_peers,
                min_share=settings.peer_min_share,
                deviations=deviations,
            )
        )
    return groups


def _dependencies(items: list[Dependency]) -> list[Dependency]:
    return [dep for item in items for dep in [item, *_dependencies(item.children)]]


def _function(symbol: Symbol, source: bytes) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.lineno >= symbol.span.start_line
        and node.end_lineno == symbol.span.end_line
        and node.name == symbol.name
    )


def _direct_call(
    function: ast.FunctionDef | ast.AsyncFunctionDef, edge: CallEdge
) -> ast.Call | None:
    """No optional branch, callback, loop or caught failure can establish a path guard."""
    for statement in function.body:
        if isinstance(statement, ast.Try | ast.With | ast.For | ast.While):
            return None
        if isinstance(statement, ast.If) and any(
            isinstance(n, ast.Return) for n in ast.walk(statement)
        ):
            return None
        if isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign | ast.Return):
            value = statement.value
            if isinstance(value, ast.Call) and value.lineno == edge.reference_line:
                return value
        if isinstance(statement, ast.Return | ast.Raise):
            return None
    return None


def _arguments(function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call) -> dict[str, str]:
    """Exact simple positional/keyword bindings, never dynamic unpacking or defaults."""
    args = [*function.args.posonlyargs, *function.args.args]
    if function.args.vararg or function.args.kwarg or len(call.args) > len(args):
        return {}
    bound = {arg.arg: dotted(value) for arg, value in zip(args, call.args, strict=False)}
    keywords = {arg.arg for arg in [*function.args.args, *function.args.kwonlyargs]}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in keywords or keyword.arg in bound:
            return {}
        bound[keyword.arg] = dotted(keyword.value)
    return (
        {name: value for name, value in bound.items() if value is not None}
        if all(bound.values())
        else {}
    )


class PeerCheck:
    def __init__(
        self,
        classifier: Classifier,
        index: Index,
        graph: CallGraph,
        settings: Settings,
        *,
        typescript_graph: CallGraph | None = None,
        infer_policy: bool = True,
    ) -> None:
        self.classifier, self.index, self.graph, self.settings = classifier, index, graph, settings
        self.snapshot, self.store = classifier.snapshot, classifier.store
        if index.meta("snapshot_id") != self.snapshot.id or graph.snapshot_id != self.snapshot.id:
            raise ValueError("peer inputs must use the same snapshot")
        self.symbols = {row.id: index.to_contract(row, self.snapshot.id) for row in index.symbols()}
        self.summaries: dict[tuple[str, str], Summary] = {}
        if typescript_graph is not None and typescript_graph.snapshot_id != self.snapshot.id:
            raise ValueError("TypeScript peer graph must use the same snapshot")
        self.typescript_graph = typescript_graph
        self.infer_policy = infer_policy

    def summary(self, symbol_id: str, resource: str) -> Summary:
        key = (symbol_id, resource)
        if key not in self.summaries:
            self.summaries[key] = self.classifier.classify(
                self.symbols[symbol_id],
                Spend(Budget(max_prompt_tokens=12000, max_seconds=240, max_retries=0)),
                resource=resource,
            )
        return self.summaries[key]

    def source(self, symbol: Symbol) -> bytes:
        return self.store.read(self.snapshot, symbol.span.path)

    def span(self, symbol: Symbol, node: ast.stmt | ast.expr) -> SourceSpan:
        start, end = node.lineno, node.end_lineno or node.lineno
        return SourceSpan(
            snapshot_id=self.snapshot.id,
            path=symbol.span.path,
            start_line=start,
            end_line=end,
            content_sha256=span_sha256(self.source(symbol), start, end),
        )

    def _binding(self, dep: Dependency, guard: Guard) -> tuple[tuple[str, ...], SourceSpan] | None:
        """Resolve the actual literal factory arguments; symbolic ROLE(roles) is insufficient."""
        if (
            not dep.factory_symbol_id
            or not dep.target_symbol_id
            or dep.status is LinkStatus.UNRESOLVED
        ):
            return None
        factory = self.symbols[dep.factory_symbol_id]
        nested = self.symbols[dep.target_symbol_id]
        node = _function(factory, self.source(factory))
        if node.args.vararg is None or node.args.vararg.arg != guard.role:
            return None
        if not (
            factory.span.path == nested.span.path
            and factory.span.start_line
            < nested.span.start_line
            <= nested.span.end_line
            < factory.span.end_line
        ):
            return None
        if (
            not isinstance(node.body[-1], ast.Return)
            or not isinstance(node.body[-1].value, ast.Name)
            or node.body[-1].value.id != nested.name
        ):
            return None
        if any(isinstance(n, ast.Assign | ast.AugAssign | ast.AnnAssign) for n in ast.walk(node)):
            return None
        source = self.store.read(self.snapshot, dep.span.path)
        tree = ast.parse(source)
        expression = ast.parse(dep.expression, mode="eval").body
        if not isinstance(expression, ast.Call) or len(expression.args) != 1:
            return None
        reference = dotted(expression.args[0])
        bindings = [
            n.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == reference
        ]
        if len(bindings) != 1 or not isinstance(bindings[0], ast.Call):
            return None
        call = bindings[0]
        if (
            call.keywords
            or not call.args
            or not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args)
        ):
            return None
        parsed = [ast.parse(value, mode="eval").body for value in dep.factory_arguments]
        if not all(isinstance(value, ast.Constant) for value in parsed):
            return None
        if [a.value for a in call.args if isinstance(a, ast.Constant)] != [
            a.value for a in parsed if isinstance(a, ast.Constant)
        ]:
            return None
        roles = tuple(
            a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
        )
        return roles, self.span(nested.model_copy(update={"span": dep.span}), call)

    def _resource_guard(self, path: AccessPath, guard: Guard) -> bool:
        """Check that the compared record/selector is the actual access, not another object."""
        if guard.via_symbol_id != path.owner_symbol_id or guard.object is None:
            return False
        symbol = self.symbols[path.owner_symbol_id]
        fn = _function(symbol, self.source(symbol))
        parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
        queries = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and n.lineno == path.site.span.start_line
        ]
        if guard.mechanism is GuardMechanism.QUERY_FILTER:
            keyed = checks(
                symbol.language, self.source(symbol), guard.span.start_line, guard.span.end_line
            )
            if any(
                c.resource == path.site.resource and (guard.object, guard.subject) in c.pairs
                for c in keyed
            ):
                return (
                    guard.span.path == path.site.span.path
                    and guard.span.start_line
                    <= path.site.span.start_line
                    <= path.site.span.end_line
                    <= guard.span.end_line
                )
            return (
                guard.object.startswith(path.site.resource + ".")
                and guard.span.start_line <= path.site.span.start_line <= guard.span.end_line
                and any(
                    isinstance(n, ast.Call)
                    and dotted(n.func) == "select"
                    and n.args
                    and dotted(n.args[0]) == path.site.resource
                    for q in queries
                    for n in ast.walk(q)
                )
            )
        for query in queries:
            parent = parents.get(query)
            while parent is not None and not isinstance(parent, ast.Assign | ast.AnnAssign):
                parent = parents.get(parent)
            targets = (
                parent.targets
                if isinstance(parent, ast.Assign)
                else [parent.target]
                if isinstance(parent, ast.AnnAssign)
                else []
            )
            if parent not in fn.body:
                continue
            if any(
                isinstance(t, ast.Name) and guard.object.startswith(t.id + ".") for t in targets
            ):
                # Reject rebinding or consuming the record before the denial.
                for prior in fn.body[fn.body.index(parent) + 1 :]:
                    if prior.lineno >= guard.span.start_line:
                        break
                    if (
                        not isinstance(prior, ast.If)
                        or prior.orelse
                        or len(prior.body) != 1
                        or not isinstance(prior.body[0], ast.Raise)
                    ):
                        return False
                return query.lineno <= guard.span.start_line
            # A caller selector check joined to this executed equality establishes tenant scope.
            for where in ast.walk(query):
                if (
                    not isinstance(where, ast.Call)
                    or not isinstance(where.func, ast.Attribute)
                    or where.func.attr != "where"
                ):
                    continue
                for n in where.args:
                    if (
                        isinstance(n, ast.Compare)
                        and len(n.ops) == 1
                        and isinstance(n.ops[0], ast.Eq)
                    ):
                        sides = {dotted(n.left), dotted(n.comparators[0])}
                        if (
                            guard.object in sides
                            and f"{path.site.resource}.{guard.object}" in sides
                        ):
                            return guard.span.end_line < query.lineno
        return False

    def _returns_principal(self, dep: Dependency, resource: str) -> bool:
        if not dep.target_symbol_id or dep.status is LinkStatus.UNRESOLVED:
            return False
        symbol = self.symbols[dep.target_symbol_id]
        fn = _function(symbol, self.source(symbol))
        if not isinstance(fn.body[-1], ast.Return) or not isinstance(fn.body[-1].value, ast.Name):
            return False
        result = fn.body[-1].value.id
        summary = self.summary(symbol.id, resource)
        if any(g.kind is GuardKind.AUTHENTICATED for g in summary.guards):
            # The returned value itself must have an enforced missing-value rejection.
            candidates = checks(
                symbol.language, self.source(symbol), symbol.span.start_line, symbol.span.end_line
            )
            return any(
                isinstance(stmt, ast.If)
                and isinstance(stmt.test, ast.Compare)
                and isinstance(stmt.test.left, ast.Name)
                and stmt.test.left.id == result
                and len(stmt.test.ops) == 1
                and isinstance(stmt.test.ops[0], ast.Is | ast.Eq)
                and isinstance(stmt.test.comparators[0], ast.Constant)
                and stmt.test.comparators[0].value is None
                and len(stmt.body) == 1
                and isinstance(stmt.body[0], ast.Raise)
                and any(c.authentication and c.start == stmt.lineno for c in candidates)
                for stmt in fn.body[-2:-1]
            )
        # A role wrapper must return the principal obtained by its actual child dependency.
        return (
            any(g.kind is GuardKind.ROLE for g in summary.guards)
            and any(
                child.parameter == result and self._returns_principal(child, resource)
                for child in dep.children
            )
            and len(fn.body) == 2
            and isinstance(fn.body[0], ast.If)
            and isinstance(fn.body[0].test, ast.Compare)
            and dotted(fn.body[0].test.left) == f"{result}.role"
        )

    def _principals(self, path: AccessPath, route: FastAPIRoute, symbol_id: str) -> set[str]:
        symbol = self.symbols[symbol_id]
        fn = _function(symbol, self.source(symbol))
        known = {
            dep.parameter
            for dep in _dependencies(route.dependencies)
            if dep.parameter is not None
            and dep.span.path == symbol.span.path
            and fn.lineno <= dep.span.start_line <= fn.body[0].lineno
            and self._returns_principal(dep, path.site.resource)
        }
        if symbol_id in path.via_symbol_ids:
            position = path.via_symbol_ids.index(symbol_id)
            if position:
                caller_id = path.via_symbol_ids[position - 1]
                caller = self.symbols[caller_id]
                upstream = self._principals(path, route, caller_id)
                for edge in self.graph.calls(caller_id):
                    if edge.target_id != symbol_id:
                        continue
                    call = _direct_call(_function(caller, self.source(caller)), edge)
                    if call:
                        bound = _arguments(fn, call)
                        known.update(
                            arg.arg
                            for arg in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
                            if bound.get(arg.arg) in upstream
                        )
        return known

    def _helper_guard(
        self, path: AccessPath, edge: CallEdge, guard: Guard, principals: set[str]
    ) -> SourceSpan | None:
        if (
            edge.target_id is None
            or edge.caller_id != path.owner_symbol_id
            or not guard.object
            or guard.via_symbol_id != edge.target_id
        ):
            return None
        caller, helper = self.symbols[edge.caller_id], self.symbols[edge.target_id]
        fn = _function(caller, self.source(caller))
        call = _direct_call(fn, edge)
        if call is None or call.lineno <= path.site.span.end_line:
            return None
        bound = _arguments(_function(helper, self.source(helper)), call)
        if not guard.subject or bound.get(guard.subject.split(".")[0]) not in principals:
            return None
        root = guard.object.split(".")[0]
        actual = bound.get(root)
        if actual is None:
            return None
        # The helper must receive this loaded record with no intervening exposure/rebinding.
        query_statement = next(
            (
                s
                for s in fn.body
                if isinstance(s, ast.Assign) and s.lineno == path.site.span.start_line
            ),
            None,
        )
        if (
            query_statement is None
            or len(query_statement.targets) != 1
            or dotted(query_statement.targets[0]) != actual
        ):
            return None
        for stmt in fn.body[fn.body.index(query_statement) + 1 :]:
            if stmt.lineno >= call.lineno:
                break
            if (
                not isinstance(stmt, ast.If)
                or stmt.orelse
                or len(stmt.body) != 1
                or not isinstance(stmt.body[0], ast.Raise)
            ):
                return None
        return self.span(caller, call)

    def build(self, access: AccessMap) -> PeerResult:
        if access.snapshot_id != self.snapshot.id:
            raise ValueError("access and peer snapshot differ")
        # Derive dependencies again; external exemption claims are not accepted.
        fastapi: FastAPIMap = extract_fastapi(self.snapshot, self.store, self.index)
        routes = {r.entry.id: r for r in fastapi.routes}
        selected = AccessMap(
            snapshot_id=access.snapshot_id,
            accesses=[
                a
                for a in access.accesses
                if a.site.key_origin in REQUEST_ORIGINS | {InputOrigin.UNKNOWN}
            ],
            issues=access.issues,
        )
        records = []
        for path in selected.accesses:
            fact = SiteChecks(site_id=path.site.id)
            records.append(fact)
            if self.symbols[path.owner_symbol_id].language is not Language.PYTHON:
                if self.typescript_graph is not None:
                    from agent.ts_paths import bind_query_guard

                    local = self.summary(path.owner_symbol_id, path.site.resource)
                    fact.issues.extend(local.issues)
                    for guard in local.guards:
                        evidence = bind_query_guard(
                            path,
                            guard,
                            self.classifier,
                            self.symbols,
                            self.typescript_graph,
                            self.summary,
                        )
                        if evidence:
                            fact.guards.append(guard)
                            fact.evidence.extend(evidence)
                if not fact.guards:
                    fact.issues.append(
                        "TypeScript caller/resource or returned receiver binding unsupported"
                    )
                else:
                    fact.issues.append(
                        "Local DAL constraint proven; identity-provider correctness "
                        "and required policy are not established"
                    )
                continue
            route = routes.get(path.site.entry_point_id)
            if route is None or self.symbols[path.owner_symbol_id].language is not Language.PYTHON:
                fact.issues.append("path propagation unsupported for this framework/language")
                continue
            if route.mount_status is LinkStatus.UNRESOLVED:
                fact.issues.append("route mounting unresolved")
                continue
            # Every non-dependency call carrying the access must be unconditional and uncaught.
            dependency_ids = {d.target_symbol_id for d in _dependencies(route.dependencies)}
            valid_path = True
            for caller, target in zip(path.via_symbol_ids, path.via_symbol_ids[1:], strict=False):
                if target in dependency_ids:
                    continue
                fn = _function(self.symbols[caller], self.source(self.symbols[caller]))
                edges = [
                    e
                    for e in self.graph.calls(caller)
                    if e.target_id == target and e.kind == "call"
                ]
                if len(edges) != 1 or _direct_call(fn, edges[0]) is None:
                    valid_path = False
            if not valid_path:
                fact.issues.append(
                    "conditional, ambiguous or caught access path; guard propagation unknown"
                )
                continue
            roles: list[tuple[str, ...]] = []
            for dep in _dependencies(route.dependencies):
                if not dep.target_symbol_id or dep.status is LinkStatus.UNRESOLVED:
                    fact.issues.append("dependency unresolved")
                    continue
                summary = self.summary(dep.target_symbol_id, path.site.resource)
                fact.issues.extend(summary.issues)
                for guard in summary.guards:
                    if guard.kind is GuardKind.AUTHENTICATED:
                        fact.guards.append(guard)
                        fact.evidence.append(dep.span)
                    elif guard.kind is GuardKind.ROLE and (bound := self._binding(dep, guard)):
                        role_values, span = bound
                        roles.append(role_values)
                        fact.guards.append(guard)
                        fact.evidence.extend([dep.span, span])
            summary = self.summary(path.owner_symbol_id, path.site.resource)
            fact.issues.extend(summary.issues)
            principals = self._principals(path, route, path.owner_symbol_id)
            for guard in summary.guards:
                if (
                    guard.subject
                    and guard.subject.split(".")[0] in principals
                    and guard.kind in (GuardKind.OWNER, GuardKind.TENANT)
                    and self._resource_guard(path, guard)
                ):
                    fact.guards.append(guard)
            for edge in self.graph.calls(path.owner_symbol_id):
                if (
                    edge.target_id is None
                    or edge.kind != "call"
                    or self.symbols[edge.target_id].language is not Language.PYTHON
                ):
                    continue
                helper = self.summary(edge.target_id, path.site.resource)
                for guard in helper.guards:
                    if guard.kind in (GuardKind.OWNER, GuardKind.TENANT) and (
                        span := self._helper_guard(path, edge, guard, principals)
                    ):
                        fact.guards.append(guard)
                        fact.evidence.append(span)
            fact.guards[:] = list({g.id: g for g in fact.guards}.values())
            fact.evidence.extend(g.span for g in fact.guards)
            exclusion = None
            if any(set(value) == {"admin"} for value in roles):
                exclusion = (
                    "Admin-only dependency: literal admin binding and enforcing role body cited"
                )
            elif roles and any(g.kind is GuardKind.TENANT for g in fact.guards):
                exclusion = (
                    "Separate tenant-scoped role policy: resource scope "
                    "and literal role binding cited"
                )
            records[-1] = fact.model_copy(update={"exclusion": exclusion})
        return PeerResult(
            snapshot_id=self.snapshot.id,
            groups=consensus(selected, records, self.settings) if self.infer_policy else [],
            checks=records,
            limitations=[
                "Peer deviations are leads requiring challenge, not verdicts",
                "Resource identities are not merged by spelling",
                "Unsupported paths remain in the voting denominator",
                "Branch/admin exclusions are candidate exceptions, not confirmed policy",
                *access.issues,
            ],
        )

"""Bound a DAL filter to its exact query and returned, null-checked receiver.

This proves a local constraint along a bounded call path, not the correctness of
the identity provider or a whole application's policy. Unsupported paths abstain.
"""

import re
from collections.abc import Callable

from tree_sitter import Node

from agent.guard_syntax import Check, _sql_executors, checks
from agent.guards import Classifier, Summary
from agent.ts_guard_forms import _client
from analysis.access import AccessPath
from analysis.access_facts import sql_access
from analysis.resolution import CallEdge, CallGraph, LinkStatus
from analysis.syntax import _parser, _text, _walk, code_only, span_sha256
from backend.contracts.code import Guard, GuardKind, GuardMechanism, SourceSpan, Symbol


def _function(symbol: Symbol, source: bytes) -> Node | None:
    root = _parser(symbol.language).parse(code_only(symbol.language, source)).root_node
    if root.has_error:
        return None
    return next(
        (
            n
            for n in _walk(root)
            if n.type == "function_declaration"
            and _text(n.child_by_field_name("name")) == symbol.name
            and n.end_point.row + 1 == symbol.span.end_line
        ),
        None,
    )


def _call(node: Node | None) -> Node | None:
    if node is not None and node.type == "await_expression":
        node = node.named_children[0] if len(node.named_children) == 1 else None
    return node if node is not None and node.type == "call_expression" else None


def _value(statement: Node) -> Node | None:
    if statement.type == "lexical_declaration" and len(statement.named_children) == 1:
        return statement.named_children[0].child_by_field_name("value")
    if (
        statement.type in ("return_statement", "expression_statement")
        and len(statement.named_children) == 1
    ):
        return statement.named_children[0]
    return None


def _direct(function: Node, line: int, denials: list[Check] | None = None) -> Node | None:
    body = function.child_by_field_name("body")
    if body is None:
        return None
    for statement in body.named_children:
        if statement.type == "if_statement" and any(
            c.mechanism is GuardMechanism.COMPARISON
            and c.start <= statement.start_point.row + 1
            and statement.end_point.row + 1 <= c.end
            for c in denials or []
        ):
            continue
        if statement.type not in (
            "lexical_declaration",
            "return_statement",
            "expression_statement",
        ):
            return None
        call = _call(_value(statement))
        if call is not None and call.start_point.row + 1 == line:
            return call
        if statement.type == "return_statement":
            return None
    return None


def _edge(graph: CallGraph, caller: str, line: int) -> CallEdge | None:
    candidates = [e for e in graph.calls(caller) if e.reference_line == line and e.kind == "call"]
    return (
        candidates[0]
        if len(candidates) == 1 and candidates[0].status is LinkStatus.RESOLVED
        else None
    )


def _query_resource(
    query: Node, classifier: Classifier, owner: Symbol, source: bytes
) -> str | None:
    callee = _text(query.child_by_field_name("function"))
    arguments = query.child_by_field_name("arguments")
    if arguments is None or not arguments.named_children:
        return None
    match = re.fullmatch(
        r"([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\.(?:findUnique|findFirst|findMany|update|delete)",
        callee,
    )
    if match and _client(source, owner.span.path, match[1], classifier.validator.source_if_present):
        return match[2]
    if callee in _sql_executors(
        source, owner.language, owner.span.path, classifier.validator.source_if_present
    ):
        sql = _text(arguments.named_children[0])
        if sql.startswith(('"', "'", "`")) and "${" not in sql:
            parsed = sql_access(sql[1:-1], include_unkeyed=True)
            return parsed[0] if parsed else None
    return None


def bind_query_guard(
    path: AccessPath,
    guard: Guard,
    classifier: Classifier,
    symbols: dict[str, Symbol],
    graph: CallGraph,
    summary: Callable[[str, str], Summary],
) -> list[SourceSpan]:
    """Return binding evidence, or no proof; never rebind a guard by name."""
    owner = symbols[path.owner_symbol_id]
    if (
        guard.kind not in (GuardKind.OWNER, GuardKind.TENANT, GuardKind.ROLE)
        or guard.mechanism not in (GuardMechanism.QUERY_FILTER, GuardMechanism.COMPARISON)
        or not guard.confirmed
        or guard.via_symbol_id != owner.id
        or (guard.kind is not GuardKind.ROLE and (not guard.subject or not guard.object))
        or path.status is LinkStatus.UNRESOLVED
        or (guard.mechanism is GuardMechanism.QUERY_FILTER and guard.span != path.site.span)
        or not path.via_symbol_ids
        or path.via_symbol_ids[-1] != owner.id
    ):
        return []
    evidence = []
    for caller_id, target_id in zip(path.via_symbol_ids, path.via_symbol_ids[1:], strict=False):
        caller = symbols[caller_id]
        source = classifier.store.read(classifier.snapshot, caller.span.path)
        function = _function(caller, source)
        edges = [e for e in graph.calls(caller_id) if e.target_id == target_id and e.kind == "call"]
        if (
            len(edges) != 1
            or edges[0].status is not LinkStatus.RESOLVED
            or function is None
            or _direct(function, edges[0].reference_line) is None
        ):
            return []
        evidence.append(edges[0].span)
    source = classifier.store.read(classifier.snapshot, owner.span.path)
    function = _function(owner, source)
    local_checks = checks(
        owner.language,
        source,
        owner.span.start_line,
        owner.span.end_line,
        path=owner.span.path,
        read=classifier.validator.source_if_present,
    )
    if (
        function is None
        or (query := _direct(function, path.site.span.start_line, local_checks)) is None
    ):
        return []
    candidates = checks(
        owner.language,
        source,
        guard.span.start_line,
        guard.span.end_line,
        path=owner.span.path,
        read=classifier.validator.source_if_present,
    )
    subject, obj = guard.subject, guard.object
    if guard.kind is GuardKind.ROLE:
        matching = [c for c in candidates if c.roles and "|".join(c.roles) == guard.role]
        if not matching or guard.span.end_line >= path.site.span.start_line:
            return []
        if _query_resource(query, classifier, owner, source) != path.site.resource:
            return []
        if matching[0].context:
            return [
                *evidence,
                guard.span,
                path.site.span,
                *[
                    SourceSpan(
                        snapshot_id=classifier.snapshot.id,
                        path=c.path,
                        start_line=c.start,
                        end_line=c.end,
                        content_sha256=span_sha256(c.source, c.start, c.end),
                    )
                    for c in matching[0].context
                ],
            ]
        nodes = [
            n
            for n in _walk(function)
            if n.type == "if_statement" and n.start_point.row + 1 == guard.span.start_line
        ]
        if len(nodes) != 1:
            return []
        condition = _text(nodes[0].child_by_field_name("condition"))
        role = re.search(r"([A-Za-z_$][\w$]*)\.[A-Za-z_$][\w$]*\s*!==?", condition)
        if role is None:
            return []
        subject = role[1]
    elif guard.mechanism is GuardMechanism.QUERY_FILTER:
        if not any(
            c.resource == path.site.resource and (guard.object, guard.subject) in c.pairs
            for c in candidates
        ):
            return []
        if obj is None or ("." in obj and obj.rsplit(".", 1)[0] != path.site.resource):
            return []
    else:
        if not any(
            (guard.object, guard.subject) in c.pairs or (guard.subject, guard.object) in c.pairs
            for c in candidates
        ):
            return []
        statement = query
        while statement.parent is not None and statement.parent != function.child_by_field_name(
            "body"
        ):
            statement = statement.parent
        if statement.type != "lexical_declaration" or len(statement.named_children) != 1:
            return []
        record = _text(statement.named_children[0].child_by_field_name("name"))
        if (
            not _text(statement).startswith("const ")
            or (obj or "").split(".")[0] != record
            or guard.span.start_line <= path.site.span.end_line
        ):
            return []
        if _query_resource(query, classifier, owner, source) != path.site.resource:
            return []
        body = function.child_by_field_name("body")
        if body is None or any(
            n.type != "if_statement"
            or not any(
                c.start == n.start_point.row + 1 and c.end == n.end_point.row + 1
                for c in candidates
            )
            for n in body.named_children
            if statement.end_byte < n.start_byte and n.start_point.row + 1 < guard.span.start_line
        ):
            return []
        evidence.append(path.site.span)
    if subject is None:
        return []
    receiver = subject.split(".")[0]
    body = function.child_by_field_name("body")
    if body is None:
        return []
    aliases: list[Node] = []
    seen = set()
    while receiver not in seen:
        seen.add(receiver)
        bindings = [
            n
            for n in body.named_children
            if n.end_byte < query.start_byte
            and re.match(rf"const\s+{re.escape(receiver)}\s*=", _text(n))
        ]
        if len(bindings) != 1:
            return []
        binding = bindings[0]
        if aliases and binding.end_byte >= aliases[-1].start_byte:
            return []
        alias = re.fullmatch(r"const\s+[A-Za-z_$][\w$]*\s*=\s*([A-Za-z_$][\w$]*);?", _text(binding))
        if alias is None:
            break
        aliases.append(binding)
        receiver = alias[1]
    else:
        return []
    if len(bindings) != 1:
        return []
    call = _call(_value(binding))
    if call is None or _text(call.child_by_field_name("arguments")) != "()":
        return []
    # Passing the receiver itself to another helper can change the principal field.
    if any(
        any(re.search(rf"\b{re.escape(name)}\b(?!\s*\.)", _text(n)) for name in seen)
        for n in body.named_children
        if binding.end_byte < n.start_byte < query.start_byte
        and n.end_byte < query.start_byte
        and n not in aliases
    ):
        return []
    arguments = query.child_by_field_name("arguments")
    sql = (
        _text(arguments.named_children[0])
        if arguments is not None and arguments.named_children
        else ""
    )
    if obj is not None and "." not in obj and (re.search(r"\bJOIN\b", sql, re.I) or "${" in sql):
        return []
    if any(
        n.type in ("assignment_expression", "augmented_assignment_expression", "update_expression")
        and any(re.search(rf"\b{re.escape(name)}\b", _text(n)) for name in seen)
        for n in _walk(function)
    ):
        return []
    edge = _edge(graph, owner.id, call.start_point.row + 1)
    if edge is None or edge.target_id is None:
        return []
    helper = symbols[edge.target_id]
    helper_source = classifier.store.read(classifier.snapshot, helper.span.path)
    helper_node = _function(helper, helper_source)
    if helper_node is None or _text(helper_node.child_by_field_name("parameters")) != "()":
        return []
    helper_body = helper_node.child_by_field_name("body")
    if helper_body is None or len(helper_body.named_children) < 3:
        return []
    first, denial, *tail = helper_body.named_children
    returned = tail[-1]
    local = re.fullmatch(
        r"const\s+([A-Za-z_$][\w$]*)\s*=\s*await\s+[A-Za-z_$][\w$]*\(\);?", _text(first)
    )
    if (
        local is None
        or re.fullmatch(
            rf"\(\s*!{re.escape(local[1])}\s*\)", _text(denial.child_by_field_name("condition"))
        )
        is None
    ):
        return []
    names = {local[1]}
    for alias in tail[:-1]:
        match = re.fullmatch(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*);?", _text(alias))
        if match is None or match[2] not in names or match[1] in names:
            return []
        names.add(match[1])
    if _text(returned).strip().rstrip(";").strip() not in {f"return {name}" for name in names}:
        return []
    authenticated = summary(helper.id, path.site.resource)
    if authenticated.issues or not any(
        g.kind is GuardKind.AUTHENTICATED
        and g.confirmed
        and g.span.start_line == denial.start_point.row + 1
        and g.span.end_line == denial.end_point.row + 1
        for g in authenticated.guards
    ):
        return []
    evidence.extend(
        [
            helper.span,
            SourceSpan(
                snapshot_id=classifier.snapshot.id,
                path=owner.span.path,
                start_line=binding.start_point.row + 1,
                end_line=binding.end_point.row + 1,
                content_sha256=span_sha256(
                    source, binding.start_point.row + 1, binding.end_point.row + 1
                ),
            ),
            guard.span,
            *[
                SourceSpan(
                    snapshot_id=classifier.snapshot.id,
                    path=owner.span.path,
                    start_line=n.start_point.row + 1,
                    end_line=n.end_point.row + 1,
                    content_sha256=span_sha256(source, n.start_point.row + 1, n.end_point.row + 1),
                )
                for n in aliases
            ],
        ]
    )
    return evidence


def bind_authentication(
    path: AccessPath,
    classifier: Classifier,
    symbols: dict[str, Symbol],
    graph: CallGraph,
    summary: Callable[[str, str], Summary],
) -> tuple[Guard, list[SourceSpan]] | None:
    """An awaited, unconditional zero-argument verifier with a returned null-checked principal."""
    if path.status is LinkStatus.UNRESOLVED or not path.via_symbol_ids:
        return None
    evidence = []
    for caller_id, target_id in zip(path.via_symbol_ids, path.via_symbol_ids[1:], strict=False):
        caller = symbols[caller_id]
        fn = _function(caller, classifier.store.read(classifier.snapshot, caller.span.path))
        edges = [e for e in graph.calls(caller_id) if e.target_id == target_id and e.kind == "call"]
        if (
            len(edges) != 1
            or edges[0].status is not LinkStatus.RESOLVED
            or fn is None
            or _direct(fn, edges[0].reference_line) is None
        ):
            return None
        evidence.append(edges[0].span)
    owner = symbols[path.owner_symbol_id]
    source = classifier.store.read(classifier.snapshot, owner.span.path)
    fn = _function(owner, source)
    if fn is None:
        return None
    local = checks(
        owner.language,
        source,
        owner.span.start_line,
        owner.span.end_line,
        path=owner.span.path,
        read=classifier.validator.source_if_present,
    )
    query = _direct(fn, path.site.span.start_line, local)
    body = fn.child_by_field_name("body")
    if (
        query is None
        or body is None
        or _query_resource(query, classifier, owner, source) != path.site.resource
    ):
        return None
    for statement in body.named_children:
        if statement.end_byte >= query.start_byte:
            break
        raw = _value(statement)
        call = _call(raw)
        if call is None or _text(call.child_by_field_name("arguments")) != "()":
            continue
        edge = _edge(graph, owner.id, call.start_point.row + 1)
        if edge is None or edge.target_id is None:
            continue
        helper = symbols[edge.target_id]
        if raw is None or raw.type != "await_expression":
            continue
        helper_fn = _function(helper, classifier.store.read(classifier.snapshot, helper.span.path))
        helper_body = helper_fn.child_by_field_name("body") if helper_fn else None
        if (
            helper_fn is None
            or _text(helper_fn.child_by_field_name("parameters")) != "()"
            or helper_body is None
            or len(helper_body.named_children) != 3
        ):
            continue
        first, denial, returned = helper_body.named_children
        principal = re.fullmatch(
            r"const\s+([A-Za-z_$][\w$]*)\s*=\s*await\s+[A-Za-z_$][\w$]*\(\);?", _text(first)
        )
        if (
            principal is None
            or _text(denial.child_by_field_name("condition")).replace(" ", "")
            != f"(!{principal[1]})"
            or _text(returned).strip().rstrip(";") != f"return {principal[1]}"
        ):
            continue
        verified = summary(helper.id, path.site.resource)
        guard = next(
            (
                g
                for g in verified.guards
                if g.kind is GuardKind.AUTHENTICATED
                and g.confirmed
                and g.span.start_line == denial.start_point.row + 1
                and g.span.end_line == denial.end_point.row + 1
            ),
            None,
        )
        if guard and not verified.issues:
            return guard, [*evidence, edge.span, helper.span, path.site.span]
    return None

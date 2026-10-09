"""Source-backed potential impact, independent of conclusion and runtime reproduction."""

from collections.abc import Mapping, Sequence

from agent.challenge import ChallengeResult
from agent.challenge import finding as authorization_finding
from agent.families import SinkInvestigator, SinkResult
from agent.peers import PeerCheck, PeerResult, SiteChecks, consensus
from agent.questions import SinkKind
from agent.validator import Unconfirmed, Validator
from analysis.access import REQUEST_ORIGINS, AccessMap, AccessPath
from analysis.fastapi import FastAPIMap, FastAPIRoute
from analysis.resolution import LinkStatus
from backend.contracts.code import Guard, GuardKind, Operation, SourceSpan
from backend.contracts.investigation import Conclusion, Exhibit, ExhibitRole, Finding, Severity


def unknown(case: Finding, reason: str) -> Finding:
    return case.model_copy(update={"severity": Severity.UNKNOWN, "severity_rationale": reason})


def _not_supported(case: Finding) -> Finding | None:
    if case.conclusion is not Conclusion.SUPPORTED:
        return unknown(case, f"Not rated: the investigation is {case.conclusion.value}.")
    return None


def _apply(
    case: Finding,
    level: Severity,
    rationale: str,
    spans: Sequence[SourceSpan],
    validator: Validator,
) -> Finding:
    if not spans or any(validator.evidence(span) for span in spans):
        return unknown(
            case, "Impact evidence does not resolve to executable code in this snapshot."
        )
    exhibits = list(case.exhibits)
    tags = []
    for span in spans:
        existing = next(
            (e for e in exhibits if e.span == span and e.role is not ExhibitRole.DEVELOPER_NOTE),
            None,
        )
        if existing:
            tags.append(existing.tag)
            continue
        number = max((int(e.tag[1:]) for e in exhibits), default=0) + 1
        if number > 999:
            return unknown(case, "Impact evidence exceeds the report's exhibit capacity.")
        tag = f"E{number:02d}"
        exhibits.append(
            Exhibit(
                tag=tag,
                span=span,
                role=ExhibitRole.EVIDENCE,
                gloss="Source used to assess potential impact",
            )
        )
        tags.append(tag)
    return case.model_copy(
        update={
            "severity": level,
            "exhibits": exhibits,
            "severity_rationale": f"Source-impact v1: {rationale} "
            f"Evidence: {', '.join(dict.fromkeys(tags))}. "
            "Deployment reachability, attacker prerequisites and runtime impact remain unverified.",
        }
    )


def authorization(
    case: Finding,
    result: ChallengeResult,
    access: AccessMap,
    peers: PeerResult,
    routes: Mapping[str, FastAPIRoute],
    checker: PeerCheck,
) -> Finding:
    if unsupported := _not_supported(case):
        return unsupported
    validator = checker.classifier.validator
    paths = {p.site.id: p for p in access.accesses}
    path = paths.get(result.site_id)
    original = authorization_finding(result, run_id=case.run_id, display_id=case.display_id)
    if (
        path is None
        or not result.evidence
        or len(paths) != len(access.accesses)
        or case != original
        or result.snapshot_id != case.snapshot_id
        or access.snapshot_id != case.snapshot_id
    ):
        return unknown(case, "The finding is not bound to this exact source access and judgment.")
    site = path.site
    route = routes.get(site.entry_point_id)
    if (
        case.snapshot_id != site.snapshot_id
        or peers.snapshot_id != case.snapshot_id
        or path.status is LinkStatus.UNRESOLVED
        or site.key_origin not in REQUEST_ORIGINS
        or route is None
        or route.mount_status is LinkStatus.UNRESOLVED
        or route.entry.snapshot_id != case.snapshot_id
        or route.entry.id != site.entry_point_id
    ):
        return unknown(
            case,
            "A request-controlled access and statically mounted HTTP entry "
            "are not both established.",
        )
    group = next(
        (g for g in peers.groups if g.id == case.peer_group_id and site.id in g.site_ids), None
    )
    if (
        group is None
        or group.resource != site.resource
        or result.resource != site.resource
        or group.snapshot_id != case.snapshot_id
    ):
        return unknown(case, "No source-bound peer group establishes this resource's access class.")
    try:
        selected = access.model_copy(update={"accesses": [paths[c.site_id] for c in peers.checks]})
        recomputed = consensus(selected, peers.checks, checker.settings)
    except (KeyError, ValueError):
        return unknown(case, "Peer membership or source identities are inconsistent.")
    if group not in recomputed or any(e.site_id == site.id for e in group.excluded):
        return unknown(
            case, "Peer votes, exclusions or thresholds do not match the source-bound records."
        )
    kinds = {d.missing for d in group.deviations if d.site_id == site.id}
    kinds &= {GuardKind.OWNER.value, GuardKind.TENANT.value}
    evidence_by_kind: dict[str, list[SourceSpan]] = {kind: [] for kind in kinds}
    voting_sites: dict[str, set[str]] = {kind: set() for kind in kinds}
    try:
        for check in peers.checks:
            if check.site_id == site.id or check.site_id not in group.site_ids or check.exclusion:
                continue
            for guard in check.guards:
                if guard.kind.value not in kinds or not guard.confirmed or guard.optimistic:
                    continue
                if not _bound_scope(checker, paths[check.site_id], guard, check):
                    return unknown(case, "A peer guard is not bound to its exact resource access.")
                validator.confirm(guard, subject=guard.subject, object=guard.object)
                voting_sites[guard.kind.value].add(check.site_id)
                evidence_by_kind[guard.kind.value].extend(
                    [paths[check.site_id].site.span, guard.span, *check.evidence]
                )
    except (Unconfirmed, ValueError):
        return unknown(case, "Peer scope evidence could not be reconfirmed from source.")
    voters = len(group.site_ids) - len(group.excluded) - 1
    kind = next(
        (
            kind
            for kind in sorted(kinds)
            if voters > 0
            and len(voting_sites[kind]) >= group.min_peers
            and len(voting_sites[kind]) / voters >= group.min_share
        ),
        None,
    )
    if kind is None:
        return unknown(
            case,
            "Insufficient cited peer scope to classify this data; "
            "names do not establish sensitivity.",
        )
    evidence = evidence_by_kind[kind]
    if site.operation in (Operation.READ, Operation.LIST):
        level, action = Severity.MEDIUM, "read"
        if route.entry.method not in ("GET", "HEAD"):
            return unknown(
                case,
                "The selected query reads data, but this handler's mutation impact "
                "is not bound to it.",
            )
    elif site.operation in (Operation.CREATE, Operation.UPDATE, Operation.DELETE):
        level, action = Severity.HIGH, "mutation"
    else:
        return unknown(case, "The operation's impact is unsupported.")
    return _apply(
        case,
        level,
        f"Potential unauthorized {action} of principal/tenant-scoped records "
        "through a declared HTTP route. "
        "The data class is inferred from executable peer restrictions, not resource names; "
        "personal/payment contents and broader compromise are not established.",
        [route.entry.span, site.span, *evidence],
        validator,
    )


def _bound_scope(checker: PeerCheck, path: AccessPath, guard: Guard, check: SiteChecks) -> bool:
    """Recheck structural record/call binding without classifying or requesting inference."""
    if guard.snapshot_id != path.site.snapshot_id or path.owner_symbol_id not in checker.symbols:
        return False
    if checker._resource_guard(path, guard):
        return True
    for edge in checker.graph.calls(path.owner_symbol_id):
        if edge.target_id != guard.via_symbol_id or not guard.subject:
            continue
        span = checker._helper_guard(path, edge, guard, {guard.subject.split(".")[0]})
        if span is not None and span in check.evidence:
            return True
    return False


def sink(
    case: Finding, result: SinkResult, investigator: SinkInvestigator, routes: FastAPIMap
) -> Finding:
    if unsupported := _not_supported(case):
        return unsupported
    match = investigator.facts.get(result.signal_id)
    from agent.families import finding

    if not result.evidence:
        return unknown(case, "No cited source operation establishes potential impact.")
    original = finding(result, run_id=case.run_id, display_id=case.display_id)
    if (
        match is None
        or case != original
        or not result.evidence
        or case.snapshot_id != investigator.snapshot.id
        or routes.snapshot_id != case.snapshot_id
    ):
        return unknown(
            case, "The source operation and HTTP exposure belong to different or missing evidence."
        )
    path, fact = match
    candidates = [
        r
        for r in routes.routes
        if r.entry.span.path == path
        and fact.start <= r.entry.span.start_line <= fact.end
        and r.entry.span.end_line == fact.end
        and r.mount_status is not LinkStatus.UNRESOLVED
    ]
    if (
        not candidates
        or fact.issues
        or not fact.risky
        or not fact.inputs
        or result.kind.value != fact.kind
        or result.family != investigator.family(result.signal_id)
        or not any(
            s.path == path and s.start_line == fact.start and s.end_line == fact.end
            for s in result.evidence
        )
    ):
        return unknown(
            case, "A controllable unsafe operation at a declared HTTP entry is not established."
        )
    if result.kind is not SinkKind.COMMAND or fact.kind != SinkKind.COMMAND.value:
        return unknown(
            case,
            "Affected data/file sensitivity and database or filesystem privileges "
            "are not established.",
        )
    return _apply(
        case,
        Severity.HIGH,
        "Request-derived text controls a shell command in a declared HTTP handler. "
        "Authority class: the application process; operation: command execution. "
        "Administrator privileges or complete host compromise are not established.",
        [*result.evidence, candidates[0].entry.span],
        investigator.validator,
    )

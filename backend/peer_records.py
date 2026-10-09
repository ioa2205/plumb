"""Project already-computed authorization checkpoints without building or judging peers."""

from pydantic import JsonValue

from agent.peers import PeerResult
from analysis.access import AccessMap
from backend.contracts.code import EntryPoint
from backend.contracts.peers import PeerComparison, PeerRow


def comparison(
    answer: dict[str, JsonValue], finding_id: str, site_id: str, question_id: str
) -> PeerComparison | None:
    keys = {"peer_result", "peer_access", "peer_entries"}
    if not keys.intersection(answer):
        return None  # legacy and non-authorization answers; no reconstruction
    if not keys.issubset(answer):
        raise ValueError("peer checkpoint metadata is incomplete")
    peers = PeerResult.model_validate(answer["peer_result"])
    judgment = answer.get("result")
    if (
        not isinstance(judgment, dict)
        or judgment.get("site_id") != site_id
        or judgment.get("snapshot_id") != peers.snapshot_id
    ):
        raise ValueError("peer checkpoint must describe the recorded challenge subject")
    access = AccessMap.model_validate(answer["peer_access"])
    raw = answer["peer_entries"]
    if not isinstance(raw, list):
        raise ValueError("peer entries must be recorded as a list")
    entries = [EntryPoint.model_validate(item) for item in raw]
    sites = {item.site.id: item.site for item in access.accesses}
    checks = {item.site_id: item for item in peers.checks}
    by_entry = {item.id: item for item in entries}
    members = [site for group in peers.groups for site in group.site_ids]
    if (
        peers.snapshot_id != access.snapshot_id
        or any(group.snapshot_id != peers.snapshot_id for group in peers.groups)
        or len(set(members)) != len(members)
        or len(sites) != len(access.accesses)
        or len(checks) != len(peers.checks)
        or len(by_entry) != len(entries)
        or set(members) != set(sites)
        or set(sites) != set(checks)
        or set(by_entry) != {site.entry_point_id for site in sites.values()}
    ):
        raise ValueError("peer checkpoint membership/snapshot associations are inconsistent")
    selected = [group for group in peers.groups if site_id in group.site_ids]
    if len(selected) != 1:
        raise ValueError("the finding subject must belong to exactly one recorded peer group")
    group = selected[0]
    return PeerComparison(
        finding_id=finding_id,
        question_id=question_id,
        subject_site_id=site_id,
        group=group,
        rows=[
            PeerRow(
                site=sites[key],
                entry=by_entry[sites[key].entry_point_id],
                guards=checks[key].guards,
                evidence=checks[key].evidence,
                exclusion=checks[key].exclusion,
                issues=checks[key].issues,
            )
            for key in group.site_ids
        ],
        limitations=list(dict.fromkeys([*peers.limitations, *access.issues])),
    )

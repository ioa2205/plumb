"""Explicit §11 development experiments; public production dispatch never selects these."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import JsonValue

from agent.boundaries import BoundaryResult
from agent.challenge import AuthorizationChallenge, ChallengeResult, Search
from agent.families import SinkResult
from agent.guards import Classifier, SummaryCache
from agent.llm import ModelRequest, Spend
from agent.peers import PeerCheck, PeerResult
from agent.questions import SinkKind
from analysis.access import REQUEST_ORIGINS, AccessMap
from analysis.syntax import span_sha256
from backend.contracts.code import Guard, GuardKind, GuardMechanism, SourceSpan
from backend.contracts.common import Family
from backend.contracts.investigation import Conclusion, Question, QuestionStage
from backend.jobs import Step
from backend.redaction import Redactor
from backend.review import Workflow

Method = Literal[
    "full_plumb", "no_peer", "no_challenge", "no_grammar", "no_self_consistency", "no_verification"
]
METHODS: tuple[Method, ...] = (
    "full_plumb",
    "no_peer",
    "no_challenge",
    "no_grammar",
    "no_self_consistency",
    "no_verification",
)


@dataclass(frozen=True)
class Unconstrained(ModelRequest):
    def body(self, redactor: Redactor | None = None) -> dict[str, Any]:
        body = super().body(redactor)
        body.pop("response_format")
        return body


def request_without_grammar(request: ModelRequest) -> ModelRequest:
    return Unconstrained(**asdict(request))


class WithoutPeers(PeerCheck):
    def build(self, access: AccessMap) -> PeerResult:
        # Subject source binding remains; peer comparisons/votes are omitted.
        self.infer_policy = False
        result = super().build(access)
        return result.model_copy(
            update={
                "groups": [],
                "limitations": [*result.limitations, "Experimental peer check omitted"],
            }
        )


class StudyWorkflow(Workflow):
    method: Method = "full_plumb"

    @property
    def challenge(self) -> AuthorizationChallenge:
        if self.method != "no_peer":
            return super().challenge
        if self._challenge is None:
            ids = {s for q in self.runs.questions(self.run_id) for s in q.subject_ids}
            access = self.review.access.model_copy(
                update={
                    "accesses": [p for p in self.review.access.accesses if p.site.id in ids],
                }
            )
            classifier = Classifier(
                self.review.snapshot,
                self.review.store,
                self.model,
                SummaryCache(self.cache),
                identity=self.identity,
            )
            self._challenge = AuthorizationChallenge(
                WithoutPeers(
                    classifier,
                    self.review.index,
                    self.review.python,
                    self.review.settings,
                    typescript_graph=self.review.typescript,
                ),
                access,
                self.model,
                policies=self.review.policies,
            )
        return self._challenge

    def handle(self, question: Question, state: Mapping[str, JsonValue], spend: Spend) -> Step:
        if self.method != "no_challenge" or question.stage is not QuestionStage.CHALLENGE:
            return super().handle(question, state, spend)
        data = dict(state)
        signal = question.subject_ids[0]
        if question.family is Family.AUTHORIZATION:
            challenge = self.challenge
            path, fact = challenge.paths[signal], challenge.facts[signal]
            cuts = challenge._cuts(signal)
            spans = [
                SourceSpan(
                    snapshot_id=self.review.snapshot.id,
                    path=c.path,
                    start_line=c.start,
                    end_line=c.end,
                    content_sha256=span_sha256(c.source, c.start, c.end),
                )
                for c in cuts
            ]
            relevant = [g for g in fact.guards if g.kind is GuardKind.OWNER]
            group = next((g for g in challenge.result.groups if signal in g.site_ids), None)
            lead = bool(
                group
                and any(d.site_id == signal and d.missing == "owner" for d in group.deviations)
            )
            conclusion = (
                Conclusion.INCONCLUSIVE
                if fact.issues or path.site.key_origin not in REQUEST_ORIGINS
                else Conclusion.REJECTED
                if relevant
                else Conclusion.SUPPORTED
                if lead
                else Conclusion.CANDIDATE
            )
            result = ChallengeResult(
                snapshot_id=self.review.snapshot.id,
                site_id=signal,
                resource=path.site.resource,
                missing=GuardKind.OWNER,
                conclusion=conclusion,
                rationale=(
                    "Experimental source/peer lead only; acquittal searches and judgments omitted"
                ),
                searches=[
                    Search(
                        item="Source-bound owner guard",
                        status="found" if relevant else "not_found",
                        searched=spans,
                        guard_ids=[g.id for g in relevant],
                        note="Static source binding only; challenge was omitted",
                    )
                ],
                samples=[],
                guards=fact.guards,
                evidence=spans,
                issues=fact.issues,
                peer_group_id=group.id if group else None,
            )
            groups = [group] if group else []
            members = set(group.site_ids) if group else {signal}
            data["peer_result"] = challenge.result.model_copy(
                update={
                    "groups": groups,
                    "checks": [c for c in challenge.result.checks if c.site_id in members],
                }
            ).model_dump(mode="json")
            accesses = [p for p in challenge.access.accesses if p.site.id in members]
            data["peer_access"] = challenge.access.model_copy(
                update={"accesses": accesses}
            ).model_dump(mode="json")
            entries = {p.site.entry_point_id for p in accesses}
            data["peer_entries"] = [
                challenge.routes[i].entry.model_dump(mode="json")
                for i in sorted(entries)
                if i in challenge.routes
            ]
        elif question.family is Family.NEXTJS_EXPOSURE:
            result = BoundaryResult(
                entry_id=signal,
                conclusion=Conclusion.INCONCLUSIVE,
                rationale="Experimental boundary challenge omitted; required flow remains unknown",
                samples=[],
                guards=[],
                issues=["No boundary acquittal/field judgments were made"],
            )
        else:
            path_name, fact = self.review.sinks.facts[signal]
            cuts = self.review.sinks.cuts(signal)
            spans = [
                SourceSpan(
                    snapshot_id=self.review.snapshot.id,
                    path=c.path,
                    start_line=c.start,
                    end_line=c.end,
                    content_sha256=span_sha256(c.source, c.start, c.end),
                )
                for c in cuts
            ]
            guards = []
            if fact.mechanism != "none_found" and not fact.issues:
                guards.append(
                    self.review.sinks.validator.confirm(
                        Guard(
                            id="guard:" + signal.split(":", 1)[1],
                            snapshot_id=self.review.snapshot.id,
                            kind=GuardKind(fact.mechanism),
                            canonical=f"{fact.mechanism}({fact.kind}, {path_name}:{fact.focus})",
                            mechanism=GuardMechanism.COMPARISON,
                            span=spans[0],
                            role=fact.kind,
                            object=str(fact.focus),
                        )
                    )
                )
            conclusion = (
                Conclusion.INCONCLUSIVE
                if fact.issues
                else Conclusion.REJECTED
                if guards
                else Conclusion.SUPPORTED
                if fact.risky
                else Conclusion.INCONCLUSIVE
            )
            result = SinkResult(
                signal_id=signal,
                family=self.review.sinks.family(signal),
                kind=SinkKind(fact.kind),
                conclusion=conclusion,
                rationale="Experimental recognized source signal only; acquittal judgments omitted",
                evidence=spans,
                guards=guards,
                samples=[],
                issues=list(fact.issues),
                flow_notes=list(fact.flow_notes),
            )
        data["result"] = result.model_dump(mode="json")
        return Step(QuestionStage.DECIDE, data, (result.rationale,))

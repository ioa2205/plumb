"""Cheap queue preparation, with reproducible observations and no fresh inference."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent.guards import Classifier, SummaryCache
from agent.llm import JsonAnswer, ModelRequest, Spend
from agent.peers import PeerCheck, PeerResult
from agent.priority import Reason, Rule, Subject, queue, subjects_from_map
from analysis.opengrep import Scan, scan
from analysis.security_signals import observe
from backend.contracts.common import Contract, Family
from backend.contracts.investigation import ObservationStatus, Question, ToolObservation
from backend.contracts.signals import SignalSet

if TYPE_CHECKING:
    from backend.review import Review


class CachedOnly:
    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        raise RuntimeError("Queue preparation must not request inference")


class Preparation(Contract):
    scan: Scan
    peers: PeerResult
    peer_observation: ToolObservation
    supplementary: SignalSet | None = None


def prepare(review: Review, run_id: str, cache: Path, identity: str) -> Preparation:
    patterns = scan(review.snapshot, review.store, review.settings, run_id)
    started = datetime.now(UTC)
    classifier = Classifier(
        review.snapshot,
        review.store,
        CachedOnly(),
        SummaryCache(cache),
        identity=identity,
        cached_only=True,
    )
    peers = PeerCheck(
        classifier,
        review.index,
        review.python,
        review.settings,
        typescript_graph=review.typescript,
    ).build(review.access)
    return Preparation(
        supplementary=observe(review.snapshot, review.store, review.settings, run_id),
        scan=patterns,
        peers=peers,
        peer_observation=ToolObservation(
            id=f"observation:{run_id}:peers",
            run_id=run_id,
            tool="cached-peer-check",
            tool_version="1",
            inputs={
                "snapshot_id": review.snapshot.id,
                "model_identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
                "cached_summaries_used": classifier.cache_hits,
                "fresh_requests": 0,
            },
            started_at=started,
            finished_at=datetime.now(UTC),
            status=ObservationStatus.OK,
            output_sha256=hashlib.sha256(peers.model_dump_json().encode()).hexdigest(),
        ),
    )


def order_questions(review: Review, questions: list[Question]) -> list[Question]:
    preparation = review.preparation
    deviations, uncertain = {}, {}
    if preparation:
        for group in preparation.peers.groups:
            for deviation in group.deviations:
                text = (
                    f"Cached peer lead: {deviation.peers_applying}/{deviation.peers_total} "
                    f"other sites apply {deviation.missing}; this site's guard is unconfirmed"
                )
                deviations[deviation.site_id] = deviations.get(deviation.site_id, "") + text + ". "
        uncertain = {
            fact.site_id: "Guard/path uncertainty: " + "; ".join(dict.fromkeys(fact.issues))
            for fact in preparation.peers.checks
            if fact.issues
        }
    subjects = {
        subject.id: subject
        for subject in subjects_from_map(
            review.map,
            deviations=deviations,
            uncertain_guards=uncertain,
        )
    }
    scheduled = []
    matched = set()
    for question in questions:
        subject = subjects.get(question.subject_ids[0])
        reasons = (
            list(subject.reasons)
            if subject
            else [
                Reason(
                    Rule.UNCERTAIN_GUARD,
                    "This source operation needs its family protection checked",
                )
            ]
        )
        if preparation:
            for signal in preparation.scan.signals:
                if signal.family is question.family and any(
                    span.snapshot_id == signal.span.snapshot_id
                    and span.path == signal.span.path
                    and span.start_line <= signal.span.end_line
                    and signal.span.start_line <= span.end_line
                    for span in question.evidence
                ):
                    reasons.append(
                        Reason(
                            Rule.TOOL_SIGNAL,
                            f"Opengrep lead ({signal.rule}) at {signal.span.path}:"
                            f"{signal.span.start_line}; requires source challenge",
                        )
                    )
                    matched.add(signal.model_dump_json())
        scheduled.append(Subject(question.id, tuple(reasons)))
    by_id = {q.id: q for q in questions}
    if preparation:
        review.scheduling_limits = [
            *preparation.scan.limitations,
            "Queue peer checks reuse validated exact-source/profile summaries only; "
            "uncached guards stay unknown until investigation.",
            f"Opengrep supplied {len(preparation.scan.signals)} cited pattern leads; "
            f"{len(matched)} overlap the selected supported questions. "
            "Other matches are not investigated by this queue. Pattern matches are not findings.",
        ]
    return [
        by_id[item.subject_id].model_copy(
            update={
                "priority_reasons": list(item.reasons),
                "exploration": item.exploration,
                "observation_ids": (
                    [preparation.scan.observation.id]
                    + (
                        [preparation.peer_observation.id]
                        if by_id[item.subject_id].family is Family.AUTHORIZATION
                        else []
                    )
                    if preparation
                    else by_id[item.subject_id].observation_ids
                ),
            }
        )
        for item in queue(scheduled, seed=review.snapshot.id)
    ]

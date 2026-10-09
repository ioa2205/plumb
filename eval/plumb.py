"""Matched full-Plumb development workflow; explicit local execution, never final evaluation.

Frozen packets are parsed as data in disposable directories. Evaluator metadata is
not passed to the investigator. Software fixtures do not establish model quality.
"""

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from agent.boundaries import BoundaryResult
from agent.challenge import ChallengeResult
from agent.families import SinkResult
from agent.guards import Ask
from agent.llm import (
    BudgetStop,
    JsonAnswer,
    ModelRequest,
    ModelUnavailable,
    PreflightRefused,
    Spend,
)
from agent.validator import Validator
from analysis.paths import check_relative
from analysis.snapshot import SnapshotStore, take_snapshot
from backend import profiles
from backend.contracts.code import ProjectSnapshot
from backend.contracts.common import Contract, Family, Sha256
from backend.contracts.investigation import (
    Budget,
    Conclusion,
    Finding,
    Question,
    QuestionStatus,
    RuntimeVerification,
)
from backend.contracts.runs import ReviewRun, RunLifecycle, RunType
from backend.preflight import PreflightResult
from backend.redaction import Redactor
from backend.review import Review, implementation_identity
from backend.run_store import RunStore
from backend.settings import Settings
from eval.ablations import METHODS, Method, StudyWorkflow, request_without_grammar
from eval.baselines import development as base
from eval.baselines.execution import ObservedAdapter, checkpoint, machine_state
from eval.candidate import RequestRecord, digest, write_new
from eval.mutation import development as corpus
from eval.proposals import saved_change
from eval.scoring.score import Prediction

LIMITATIONS = [
    "Development only; final corpus, measured comparison and sealed evaluation remain open.",
    "Fixture/replay accounting is not fresh model accuracy or a release acceptance pass.",
    "Source review has no general isolated verification; no runtime benefit is measured.",
    "Single-entry packets may lack peer consensus; absent/unsupported paths are abstentions.",
    "Allowed-client-field policies cannot yet be represented by the production forbidden-field "
    "contract; those packets abstain rather than invent requirements or silently ignore them.",
]


def identity() -> dict[str, str]:
    return {
        **implementation_identity(),
        **{
            name: corpus.sha((corpus.ROOT / name).read_bytes())
            for name in (
                "eval/plumb.py",
                "eval/proposals.py",
                "eval/ablations.py",
                "eval/baselines/development.py",
                "eval/baselines/execution.py",
                "eval/candidate.py",
                "eval/scoring/score.py",
                "eval/scoring/stats.py",
                "eval/bench/machine.py",
                "backend/jobs.py",
                "backend/run_store.py",
                "backend/settings.py",
                "backend/redaction.py",
                "backend/llama_server.py",
                "uv.lock",
            )
        },
    }


class Plan(Contract):
    scope: Literal["matched_plumb_development"] = "matched_plumb_development"
    final_candidate: Literal[False] = False
    method: Method = "full_plumb"
    preparation_sha256: Sha256
    pipeline: dict[str, Sha256]
    max_requests: int = Field(strict=True, gt=0, le=1000)
    judgments: Literal[0, 1, 3] = 3
    peer_min_peers: Literal[3] = 3
    peer_min_share: float = Field(default=0.75, strict=True, ge=0.75, le=0.75)
    limitations: list[str] = Field(default_factory=lambda: list(LIMITATIONS))

    @model_validator(mode="after")
    def _method(self) -> "Plan":
        expected = (
            0 if self.method == "no_challenge" else 1 if self.method == "no_self_consistency" else 3
        )
        if self.judgments != expected:
            raise ValueError("Experiment judgment count differs; production remains three")
        return self


def prepare(
    prepared: base.Preparation, max_requests: int, *, method: Method = "full_plumb"
) -> Plan:
    base.check(prepared)
    return Plan(
        preparation_sha256=digest(prepared),
        pipeline=identity(),
        max_requests=max_requests,
        method=method,
        judgments=0 if method == "no_challenge" else 1 if method == "no_self_consistency" else 3,
    )


def check(prepared: base.Preparation, plan: Plan) -> list[base.Packet]:
    plan = Plan.model_validate(plan.model_dump())
    packets = base.check(prepared)
    if plan.preparation_sha256 != digest(prepared) or plan.pipeline != identity():
        raise ValueError("Full-Plumb input/engine/budget identity changed; prepare new inputs")
    return packets


class Record(Contract):
    # Mutable in-flight evaluation checkpoints, never application run entities.
    model_config = ConfigDict(frozen=False, extra="forbid", validate_assignment=True)
    case_id: str
    packet_sha256: Sha256
    state: Literal["completed", "failed", "unrun", "unsupported"] = "unrun"
    reason: str = Field(default="Not attempted", min_length=1, max_length=1000)
    snapshot: ProjectSnapshot | None = None
    questions: list[Question] = Field(default=[], max_length=100)
    requests: list[RequestRecord] = Field(default=[], max_length=1000)
    seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


class Execution(Contract):
    model_config = ConfigDict(frozen=False, extra="forbid", validate_assignment=True)
    scope: Literal["matched_plumb_development_execution"] = "matched_plumb_development_execution"
    final_candidate: Literal[False] = False
    plan_sha256: Sha256
    evidence_kind: Literal["local_execution", "software_fixture"]
    state: Literal["completed", "failed", "unrun"] = "unrun"
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    records: list[Record] = Field(min_length=2, max_length=1000)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    machine_start: dict[str, JsonValue] = Field(default_factory=dict)
    machine_end: dict[str, JsonValue] = Field(default_factory=dict)
    observations: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None


def snapshot(packet: base.Packet, folder: Path) -> tuple[ProjectSnapshot, SnapshotStore]:
    """Only exact public source bytes; no imports, target scripts or dependency installation."""
    root = folder / "source"
    root.mkdir()
    for name, source in packet.sources.items():
        path = root.joinpath(*check_relative(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode())
    store = SnapshotStore(folder / "data/cache/snapshots")
    result = take_snapshot(root, store)
    if {f.path: f.sha256 for f in result.files} != {
        p: corpus.sha(s.encode()) for p, s in packet.sources.items()
    } or result.excluded:
        raise ValueError("Snapshot does not retain the exact matched packet")
    return result, store


class Observed(Ask):
    def __init__(
        self,
        model: Ask,
        execution: Execution,
        plan: Plan,
        prepared: base.Preparation,
        output: Path,
        clock: Callable[[], float],
        started: float,
        redactor: Redactor,
    ) -> None:
        self.model, self.execution, self.plan = model, execution, plan
        self.prepared, self.output, self.clock, self.started = prepared, output, clock, started
        self.redactor = redactor
        self.record: Record | None = None
        self.stopped = False

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        if self.plan.method == "no_grammar":
            request = request_without_grammar(request)
        remaining = self.prepared.max_seconds - (self.clock() - self.started)
        count = sum(len(r.requests) for r in self.execution.records)
        if self.stopped or remaining <= 0 or count >= self.plan.max_requests:
            self.stopped = True
            raise BudgetStop("seconds", "Declared batch request/time limit reached")
        body = request.body(self.redactor)
        if self.redactor.text(request.user) != request.user or (
            self.redactor.text(request.system) != request.system
        ):
            raise ValueError("Redaction would change matched source input")
        if self.record is None:
            raise ValueError("No exact case is active")
        # The checkpoint reserves this attempt before the transport. No retries.
        trace = RequestRecord(
            case_id=self.record.case_id,
            body=body,
            error="Attempt interrupted before a usable answer",
            prompt_tokens=0,
            completion_tokens=0,
            seconds=0,
        )
        self.record.requests.append(trace)
        if len(self.execution.model_dump_json().encode()) > base.MAX_BYTES - 1_000_000:
            self.record.requests.pop()
            self.stopped = True
            raise BudgetStop("seconds", "Aggregate execution record budget reached")
        checkpoint(self.output, self.execution)
        began = self.clock()
        spend.budget = spend.budget.model_copy(
            update={
                "max_seconds": spend.seconds + min(spend.seconds_left, remaining),
                "max_retries": 0,
            }
        )
        before_prompt, before_completion = spend.prompt_tokens, spend.completion_tokens
        if isinstance(self.model, ObservedAdapter):
            self.model.raw = None
        try:
            answer = self.model.ask(request, spend)
            data = self.redactor.strings(answer.data)
            raw = self.redactor.text(answer.raw)
            if data != answer.data or raw != answer.raw:
                raise ValueError("Redaction would change model judgment")
            self.record.requests[-1] = RequestRecord(
                case_id=self.record.case_id,
                body=body,
                answer=data,
                raw_answer=raw,
                prompt_tokens=answer.prompt_tokens,
                completion_tokens=answer.completion_tokens,
                seconds=self.clock() - began,
            )
            return answer
        except BaseException as error:
            if isinstance(error, (ModelUnavailable, PreflightRefused)):
                self.stopped = True
            raw = self.model.raw if isinstance(self.model, ObservedAdapter) else None
            self.record.requests[-1] = trace.model_copy(
                update={
                    "error": f"Request refused ({type(error).__name__})",
                    "raw_answer": raw[:100000] if raw else None,
                    "prompt_tokens": spend.prompt_tokens - before_prompt,
                    "completion_tokens": spend.completion_tokens - before_completion,
                    "seconds": self.clock() - began,
                }
            )
            raise
        finally:
            if len(self.execution.model_dump_json().encode()) > base.MAX_BYTES - 500_000:
                self.stopped = True
            checkpoint(self.output, self.execution)


def run_packet(
    packet: base.Packet, record: Record, observed: Observed, folder: Path, node: Path
) -> None:
    # EvidencePacket redacts before requests are built. Check the original packet
    # first so that already-redacted prompts cannot masquerade as identical inputs.
    if any(observed.redactor.text(text) != text for text in packet.sources.values()):
        raise ValueError("Redaction would change the exact matched source packet")
    frozen, _ = snapshot(packet, folder)
    record.snapshot = frozen
    if packet.allowed_client_fields:
        record.state, record.reason = "unsupported", LIMITATIONS[-1]
        return
    settings = Settings(
        data_dir=(folder / "data").resolve(),
        node_binary=node,
        peer_min_peers=observed.plan.peer_min_peers,
        peer_min_share=observed.plan.peer_min_share,
    )
    review = Review(settings, frozen.id)
    try:
        run_id = "run:" + packet.sha256
        # Dispatch all families, without consulting the evaluator's expected family/label.
        questions, coverage, _ = review.questions(run_id, [], [], tuple(Family))
        focus = packet.focus
        questions = [
            q
            for q in questions
            if any(
                s.path == focus.path
                and s.start_line <= focus.end_line
                and focus.start_line <= s.end_line
                for s in q.evidence
            )
        ]
        if not questions:
            record.state, record.reason = (
                "unsupported",
                "No supported review question binds to the focus entry",
            )
            return
        left = observed.prepared.max_seconds - (observed.clock() - observed.started)
        if left <= 0:
            raise BudgetStop("seconds", "Batch time limit reached during source preparation")
        questions = [
            q.model_copy(
                update={
                    "budget": Budget(
                        max_looks=q.budget.max_looks,
                        max_prompt_tokens=q.budget.max_prompt_tokens,
                        max_seconds=min(q.budget.max_seconds, left),
                        max_retries=0,
                    )
                }
            )
            for q in questions
        ]
        runs = RunStore(folder / "runs.sqlite")
        runs.create(
            ReviewRun(
                id=run_id,
                snapshot_id=frozen.id,
                run_type=RunType.LIVE,
                lifecycle=RunLifecycle.QUEUED,
                created_at=datetime.now(UTC),
                coverage=coverage,
            ),
            questions,
        )
        workflow = StudyWorkflow(
            review,
            runs,
            run_id,
            observed,
            folder / "guards.sqlite",
            digest(observed.plan),
            len(questions),
            judgments=observed.plan.judgments or 3,
        )
        workflow.method = observed.plan.method
        workflow.run()
        record.questions = runs.questions(run_id)
        answered = all(q.status is QuestionStatus.ANSWERED for q in record.questions)
        record.state = "completed" if answered else "failed"
        record.reason = (
            ("Production" if observed.plan.method == "full_plumb" else "Experimental")
            + " source workflow completed"
            if answered
            else "Review retains unanswered/failed questions"
        )
    finally:
        review.close()


def execute(
    prepared: base.Preparation,
    plan: Plan,
    output: Path,
    settings: Settings,
    *,
    fixture_model: Ask | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Execution:
    packets = check(prepared, plan)
    began = clock()
    execution = Execution(
        plan_sha256=digest(plan),
        evidence_kind="software_fixture" if fixture_model is not None else "local_execution",
        started_at=datetime.now(UTC),
        records=[
            Record(case_id=c.id, packet_sha256=p.sha256)
            for c, p in zip(prepared.cases, packets, strict=True)
        ],
    )
    write_new(output, execution)  # Exclusive before creating scratch, diagnostics or processes.
    server = None
    observed = None
    try:
        if plan.method == "no_verification":
            execution.observations["unavailable"] = (
                "Verification ablation unrun: the full-Plumb control has no available general "
                "runtime verification stage; identical source-only runs cannot measure its benefit"
            )
            return execution
        execution.machine_start = {"software_fixture": True} if fixture_model else machine_state()
        remaining = prepared.max_seconds - (clock() - began)
        if remaining <= 0:
            raise TimeoutError("Batch budget elapsed before initialization")
        model: Ask
        if fixture_model is not None:
            model = fixture_model
        else:
            name = "plumb-evaluation-" + uuid4().hex
            execution.observations["log_id"] = name
            server = profiles.create(settings, name, profiles.Profile())
            server.startup_timeout = min(server.startup_timeout, remaining)

            def preflight() -> PreflightResult:
                result = server.preflight()
                execution.observations["preflight"] = asdict(result)
                return result

            model = ObservedAdapter(server, preflight=preflight)
            model.start()
            execution.observations["load_seconds"] = server.load_seconds
        observed = Observed(
            model, execution, plan, prepared, output, clock, began, Redactor.configured()
        )
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        for number, (packet, record) in enumerate(zip(packets, execution.records, strict=True)):
            if (
                number >= prepared.max_attempts
                or observed.stopped
                or clock() - began >= prepared.max_seconds
            ):
                execution.error = "Declared batch attempt/request/time limit reached"
                break
            case_started = clock()
            observed.record = record
            record.state, record.reason = "failed", "Interrupted before source workflow completed"
            checkpoint(output, execution)
            try:
                with tempfile.TemporaryDirectory(
                    prefix="plumb-packet-", dir=settings.cache_dir
                ) as directory:
                    run_packet(packet, record, observed, Path(directory), settings.node_binary)
            except Exception as error:
                record.state, record.reason = "failed", f"Packet refused ({type(error).__name__})"
            finally:
                record.seconds = clock() - case_started
                checkpoint(output, execution)
    except BaseException as error:
        execution.error = f"Batch refused ({type(error).__name__})"
    finally:
        if server is not None:
            try:
                server.stop()
                if server.sampler is not None:
                    execution.observations["peak_working_set_bytes"] = (
                        server.sampler.peak_working_set
                    )
                    execution.observations["peak_private_bytes"] = server.sampler.peak_private
            except Exception as error:
                execution.error = f"Model teardown failed ({type(error).__name__})"
        try:
            execution.machine_end = (
                {}
                if plan.method == "no_verification"
                else {"software_fixture": True}
                if fixture_model
                else machine_state()
            )
        except Exception:
            execution.observations["machine_end"] = "unavailable"
        execution.finished_at = datetime.now(UTC)
        execution.elapsed_seconds = clock() - began
        execution.state = (
            "unrun"
            if plan.method == "no_verification"
            else (
                "failed"
                if execution.error
                or execution.elapsed_seconds > prepared.max_seconds
                or any(r.state != "completed" for r in execution.records)
                else "completed"
            )
        )
        checkpoint(output, execution)
    return execution


def account(prepared: base.Preparation, plan: Plan, execution: Execution) -> dict[str, JsonValue]:
    packets = check(prepared, plan)
    run = Execution.model_validate(execution.model_dump())
    if run.plan_sha256 != digest(plan):
        raise ValueError("Execution belongs to a different matched plan")
    if run.finished_at is None or run.finished_at < run.started_at:
        raise ValueError("Accounting requires a finished, ordered execution record")
    records = {r.case_id: r for r in run.records}
    if plan.method == "no_verification" and (
        run.state != "unrun"
        or any(r.state != "unrun" for r in run.records)
        or not run.observations.get("unavailable")
    ):
        raise ValueError("Unavailable verification ablation must remain explicitly unrun")
    if len(records) != len(run.records) or set(records) != {c.id for c in prepared.cases}:
        raise ValueError("Retain exactly every selected case denominator")
    exceeded = (
        len([r for r in run.records if r.state != "unrun"]) > prepared.max_attempts
        or sum(len(r.requests) for r in run.records) > plan.max_requests
        or run.elapsed_seconds > prepared.max_seconds
        or sum(r.seconds for r in run.records) > prepared.max_seconds
        or sum(a.seconds for r in run.records for a in r.requests) > prepared.max_seconds
    )
    if exceeded and run.state != "failed":
        raise ValueError("Budget overrun must remain a failed batch")
    if run.state == "completed" and (run.error or any(r.state != "completed" for r in run.records)):
        raise ValueError("Incomplete execution cannot claim completion")
    if run.state == "unrun" and any(r.state != "unrun" for r in run.records):
        raise ValueError("Unrun execution cannot claim processed cases")
    preflight_record = run.observations.get("preflight")
    if (
        run.evidence_kind == "local_execution"
        and run.state == "completed"
        and (
            not run.machine_start
            or not run.machine_end
            or not isinstance(preflight_record, dict)
            or preflight_record.get("ok") is not True
        )
    ):
        raise ValueError("Local completion requires observed machine and passed preflight records")
    predictions: list[Prediction] = []
    states: dict[str, str] = {}
    for case, packet in zip(prepared.cases, packets, strict=True):
        record = records[case.id]
        if record.packet_sha256 != packet.sha256 or any(
            a.case_id != case.id for a in record.requests
        ):
            raise ValueError("Output/requests bind to a different exact packet")
        if record.state == "unrun" and (
            record.questions or record.requests or record.snapshot or record.seconds
        ):
            raise ValueError("Unrun record cannot contain attempted evidence")
        states[case.id] = record.state
        path = f"case-{packet.sha256}/{packet.focus.path}"
        if record.state != "completed":
            predictions.append(
                Prediction(
                    family=case.family,
                    path=path,
                    start_line=packet.focus.start_line,
                    end_line=packet.focus.end_line,
                    conclusion=Conclusion.INCONCLUSIVE,
                )
            )
            continue
        if any(
            a.error is not None or json.loads(a.raw_answer or "") != a.answer
            for a in record.requests
        ):
            raise ValueError("Completed workflow requires exact usable raw answers")
        if any(
            ("response_format" in a.body) == (plan.method == "no_grammar") for a in record.requests
        ):
            raise ValueError("Raw request grammar mode differs from the pinned experiment")
        if (
            not record.questions
            or not record.requests
            or record.snapshot is None
            or packet.allowed_client_fields
        ):
            raise ValueError(
                "Completed workflow requires source, questions, raw attempts and supported policy"
            )
        if len({q.id for q in record.questions}) != len(record.questions):
            raise ValueError("Duplicate review questions")
        with tempfile.TemporaryDirectory(prefix="plumb-account-") as directory:
            frozen, store = snapshot(packet, Path(directory))
            if frozen.id != record.snapshot.id or frozen.files != record.snapshot.files:
                raise ValueError("Recorded review source differs from exact packet")
            validator = Validator(frozen, store)
            for question in record.questions:
                if question.status is not QuestionStatus.ANSWERED or not question.answer:
                    raise ValueError("Completed workflow contains unanswered questions")
                finding = Finding.model_validate(question.answer["finding"])
                result = (
                    ChallengeResult.model_validate(question.answer["result"])
                    if question.family is Family.AUTHORIZATION
                    else BoundaryResult.model_validate(question.answer["result"])
                    if question.family is Family.NEXTJS_EXPOSURE
                    else SinkResult.model_validate(question.answer["result"])
                )
                subject = (
                    result.site_id
                    if isinstance(result, ChallengeResult)
                    else result.entry_id
                    if isinstance(result, BoundaryResult)
                    else result.signal_id
                )
                if (
                    question.subject_ids != [subject]
                    or result.conclusion is not finding.conclusion
                    or len(result.samples) != plan.judgments
                ):
                    raise ValueError("Finding/result/sample identity differs from exact question")
                for sample in result.samples:
                    if not any(
                        a.answer == sample.answer.model_dump(mode="json")
                        and a.body.get("seed") == sample.seed
                        for a in record.requests
                    ):
                        raise ValueError("Judgment lacks its exact raw request/seed record")
                if (
                    plan.method == "no_peer"
                    and isinstance(result, ChallengeResult)
                    and (result.peer_group_id is not None or finding.peer_group_id is not None)
                ):
                    raise ValueError("Peer ablation cannot carry a peer policy vote")
                guards = result.guards
                for guard in guards:
                    validator.confirm(guard, subject=guard.subject, object=guard.object)
                change = saved_change(question, finding, record.requests, frozen, store)
                if (
                    finding.run_id != question.run_id
                    or finding.question_ids != [question.id]
                    or finding.family is not question.family
                    or finding.runtime_verification is not RuntimeVerification.NOT_ATTEMPTED
                    or finding.probe_run_ids
                    or finding.policy_basis
                    or validator.finding(finding, guards=guards, change=change)
                ):
                    raise ValueError("Finding failed exact workflow/source/runtime association")
                for span in question.evidence:
                    if validator.evidence(span):
                        raise ValueError("Question source evidence changed")
                # Predictions preserve all conclusions and off-focus positive reports.
                source = next(
                    (e.span for e in finding.exhibits if e.span.path == packet.focus.path), None
                )
                if source is None:
                    raise ValueError("Finding has no exact focus-file citation")
                predictions.append(
                    Prediction(
                        family=finding.family,
                        path=path,
                        start_line=source.start_line,
                        end_line=source.end_line,
                        conclusion=finding.conclusion,
                    )
                )
    return {
        "method": plan.method,
        "experimental_method": plan.method != "full_plumb",
        "evidence_kind": run.evidence_kind,
        "state": run.state,
        "release_acceptance": "unassessed",
        "budget_exceeded": exceeded,
        "metrics": base.matched_metrics(prepared, packets, states, predictions),
        "unprocessed_cases": [r.case_id for r in run.records if r.state != "completed"],
        "limitations": list(plan.limitations),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check", "run", "account"):
        command = commands.add_parser(name)
        command.add_argument("preparation", type=Path)
        if name == "prepare":
            command.add_argument("--max-requests", type=int, required=True)
            command.add_argument("--method", choices=METHODS, default="full_plumb")
        else:
            command.add_argument("plan", type=Path)
        if name == "account":
            command.add_argument("execution", type=Path)
        if name in {"prepare", "run", "account"}:
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepared = read_record(args.preparation, base.Preparation)
        if args.command == "prepare":
            write_new(args.output, prepare(prepared, args.max_requests, method=args.method))
            return 0
        plan = read_record(args.plan, Plan)
        if args.command == "check":
            check(prepared, plan)
        elif args.command == "run":
            result = execute(prepared, plan, args.output, Settings())
            return 0 if result.state == "completed" else 1
        else:
            result = read_record(args.execution, Execution)
            write_new(args.output, account(prepared, plan, result))
        return 0
    except (OSError, ValueError) as error:
        print(f"Matched Plumb refused: {type(error).__name__}", file=sys.stderr)
        return 1


def read_record[T: Contract](path: Path, model: type[T]) -> T:
    if path.stat().st_size > base.MAX_BYTES:
        raise ValueError("Matched record exceeds size budget")
    raw = path.read_bytes()
    if len(raw) > base.MAX_BYTES:
        raise ValueError("Matched record exceeds size budget")
    return model.model_validate_json(raw)


if __name__ == "__main__":
    raise SystemExit(main())

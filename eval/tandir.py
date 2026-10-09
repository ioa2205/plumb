"""Bounded production-workflow acceptance on frozen human-reviewed Tandir development data."""

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue

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
from analysis.snapshot import SnapshotStore
from backend import profiles
from backend.contracts.common import Contract, Family, Sha256
from backend.contracts.investigation import Finding, Question, QuestionStatus, RuntimeVerification
from backend.contracts.runs import Coverage, ReviewRun, RunLifecycle, RunType
from backend.preflight import PreflightResult
from backend.redaction import Redactor
from backend.review import Review, Workflow
from backend.run_store import RunStore
from backend.settings import Settings
from eval import candidate
from eval.baselines.execution import ObservedAdapter, checkpoint, machine_state
from eval.plumb import Record, read_record
from eval.proposals import saved_change
from eval.scoring.score import Prediction


def identity() -> dict[str, str]:
    return {
        name: hashlib.sha256((candidate.ROOT / name).read_bytes()).hexdigest()
        for name in (
            "eval/tandir.py",
            "eval/requirements.py",
            "eval/plumb.py",
            "eval/proposals.py",
            "eval/baselines/execution.py",
            "eval/bench/machine.py",
            "backend/jobs.py",
            "backend/run_store.py",
            "backend/settings.py",
            "backend/redaction.py",
            "backend/llama_server.py",
            "backend/vulkan_profile.py",
            "backend/profiles.py",
            "agent/llm.py",
        )
    }


class Execution(Contract):
    model_config = ConfigDict(frozen=False, extra="forbid", validate_assignment=True)
    scope: Literal["tandir_production_development"] = "tandir_production_development"
    final_candidate: Literal[False] = False
    preparation_sha256: Sha256
    driver: dict[str, Sha256]
    evidence_kind: Literal["fresh_local", "software_fixture"]
    state: Literal["completed", "failed", "preflight_refused", "unrun"] = "unrun"
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    machine_start: dict[str, JsonValue] = Field(default_factory=dict)
    machine_end: dict[str, JsonValue] = Field(default_factory=dict)
    observations: dict[str, JsonValue] = Field(default_factory=dict)
    records: list[Record] = Field(min_length=2, max_length=100)
    error: str | None = None


class Recorder(Ask):
    def __init__(
        self,
        model: Ask,
        prepared: candidate.Preparation,
        execution: Execution,
        output: Path,
        clock: Callable[[], float],
        began: float,
    ) -> None:
        self.model, self.prepared, self.execution = model, prepared, execution
        self.output, self.clock, self.began = output, clock, began
        self.record: Record | None = None
        self.stopped = False
        self.redactor = Redactor.configured()

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        remaining = self.prepared.max_seconds - (self.clock() - self.began)
        count = sum(len(r.requests) for r in self.execution.records)
        if self.stopped or remaining <= 0 or count >= self.prepared.max_requests:
            self.stopped = True
            raise BudgetStop("seconds", "Predeclared Tandir request/time limit reached")
        if self.record is None:
            raise ValueError("No exact development case selected")
        if self.redactor.text(request.user) != request.user or (
            self.redactor.text(request.system) != request.system
        ):
            raise ValueError("Redaction would change the frozen development evidence")
        trace = candidate.RequestRecord(
            case_id=self.record.case_id,
            body=request.body(self.redactor),
            error="Attempt interrupted before a usable answer",
            prompt_tokens=0,
            completion_tokens=0,
            seconds=0,
        )
        self.record.requests.append(trace)
        if len(self.execution.model_dump_json().encode()) > candidate.MAX_BYTES - 1_000_000:
            self.record.requests.pop()
            self.stopped = True
            raise BudgetStop("seconds", "Execution record size limit reached")
        checkpoint(self.output, self.execution)
        spend.budget = spend.budget.model_copy(
            update={
                "max_seconds": spend.seconds + min(spend.seconds_left, remaining),
                "max_retries": 0,
            }
        )
        started = self.clock()
        before_prompt, before_completion = spend.prompt_tokens, spend.completion_tokens
        if isinstance(self.model, ObservedAdapter):
            self.model.raw = None
        try:
            answer = self.model.ask(request, spend)
            if self.redactor.strings(answer.data) != answer.data or (
                self.redactor.text(answer.raw) != answer.raw
            ):
                raise ValueError("Redaction would change the saved judgment")
            self.record.requests[-1] = trace.model_copy(
                update={
                    "answer": answer.data,
                    "raw_answer": answer.raw,
                    "error": None,
                    "prompt_tokens": answer.prompt_tokens,
                    "completion_tokens": answer.completion_tokens,
                    "seconds": self.clock() - started,
                }
            )
            print(f"{self.record.case_id}: {request.name} ({count + 1} requests)", flush=True)
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
                    "seconds": self.clock() - started,
                }
            )
            raise
        finally:
            if len(self.execution.model_dump_json().encode()) > candidate.MAX_BYTES - 500_000:
                self.stopped = True
            checkpoint(self.output, self.execution)


def overlaps(question: Question, case: candidate.CaseInput) -> bool:
    return any(
        s.snapshot_id == case.source.snapshot_id
        and s.path == case.source.path
        and s.start_line <= case.source.end_line
        and case.source.start_line <= s.end_line
        for s in question.evidence
    )


def focus_questions(
    review: Review, case: candidate.CaseInput, questions: Sequence[Question]
) -> list[Question]:
    """Select exact entry accesses, including queries reached through helpers."""
    if case.source.snapshot_id != review.snapshot.id:
        return []
    if case.family is not Family.AUTHORIZATION:
        return [q for q in questions if q.family is case.family and overlaps(q, case)]
    paths = {p.site.id: p for p in review.access.accesses}
    calls = {(e.caller_id, e.target_id) for e in review.python.edges if e.kind == "call"}
    selected = []
    for question in questions:
        if question.family is not case.family or len(question.subject_ids) != 1:
            continue
        path = paths.get(question.subject_ids[0])
        site = path.site if path else None
        route = review.routes.get(site.entry_point_id) if site else None
        if (
            site is None
            or route is None
            or site.snapshot_id != review.snapshot.id
            or route.entry.snapshot_id != review.snapshot.id
            or route.entry.span != case.source
            or question.evidence != [site.span]
            or path is None
            or not path.via_symbol_ids
            or path.via_symbol_ids[0] != route.entry.handler_symbol_id
            or path.via_symbol_ids[-1] != path.owner_symbol_id
            or any(
                edge not in calls
                for edge in zip(path.via_symbol_ids, path.via_symbol_ids[1:], strict=False)
            )
        ):
            continue
        evidence = list(question.evidence)
        if case.source not in evidence:
            evidence.append(case.source)
        selected.append(question.model_copy(update={"evidence": evidence}))
    return selected


@contextmanager
def frozen_review(
    prepared: candidate.Preparation, store: SnapshotStore, settings: Settings
) -> Iterator[tuple[Path, Review]]:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tandir-development-", dir=settings.cache_dir) as name:
        folder = Path(name)
        local = Settings(data_dir=folder / "data", node_binary=settings.node_binary)
        frozen = SnapshotStore(local.cache_dir / "snapshots")
        for file in prepared.snapshot.files:
            frozen.blobs.put(store.read(prepared.snapshot, file.path))
        frozen.save(prepared.snapshot)
        review = Review(local, prepared.snapshot.id)
        try:
            if prepared.requirements is not None:
                from eval.requirements import freeze

                canonical = freeze(review, [c.source for c in prepared.cases], prepared.created_at)
                if canonical != prepared.requirements:
                    raise ValueError("development requirement/source binding changed")
                review.policies = canonical
                review.validate_policies()
            yield folder, review
        finally:
            review.close()


def execute(
    prepared: candidate.Preparation,
    store: SnapshotStore,
    output: Path,
    settings: Settings,
    *,
    fixture_model: Ask | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Execution:
    candidate.check(prepared, store)  # Before diagnostics, scratch or model processes.
    began = clock()
    execution = Execution(
        preparation_sha256=candidate.digest(prepared),
        driver=identity(),
        evidence_kind="software_fixture" if fixture_model is not None else "fresh_local",
        started_at=datetime.now(UTC),
        records=[Record(case_id=c.id, packet_sha256=c.input_id) for c in prepared.cases],
    )
    candidate.write_new(output, execution)
    server = None
    refused = False
    try:
        execution.machine_start = {"software_fixture": True} if fixture_model else machine_state()
        with frozen_review(prepared, store, settings) as (folder, review):
            # Finish static compiler/index preparation before loading the model.
            planned: list[list[Question]] = []
            for case in prepared.cases:
                run_id = "run:" + case.input_id
                questions, _, _ = review.questions(run_id, [], [], tuple(Family))
                # Family is the declared review scope, never the expected verdict.
                planned.append(focus_questions(review, case, questions))
            remaining = prepared.max_seconds - (clock() - began)
            if remaining <= 0:
                raise BudgetStop("seconds", "Time limit reached during static preparation")
            model: Ask
            if fixture_model is not None:
                model = fixture_model
            else:
                log_id = "tandir-development-" + uuid4().hex
                execution.observations["log_id"] = log_id
                try:
                    server = profiles.create(settings, log_id, profiles.Profile())
                except ValueError as error:
                    # Selection can refuse before a server/preflight exists.
                    execution.observations["profile_refusal"] = Redactor.configured().text(
                        str(error)
                    )
                    raise
                launch: list[JsonValue] = [arg for arg in server.config.argv(0, "<per-launch key>")]
                execution.observations["server_argv"] = launch
                server.startup_timeout = min(server.startup_timeout, remaining)

                def preflight() -> PreflightResult:
                    result = server.preflight()
                    execution.observations["preflight"] = asdict(result)
                    return result

                model = ObservedAdapter(server, preflight=preflight)
                model.start()
                execution.observations["load_seconds"] = server.load_seconds
            recorder = Recorder(model, prepared, execution, output, clock, began)
            for case, record, questions in zip(
                prepared.cases, execution.records, planned, strict=True
            ):
                if recorder.stopped or clock() - began >= prepared.max_seconds:
                    execution.error = "Predeclared budget/process stop reached"
                    break
                started = clock()
                record.snapshot = prepared.snapshot
                record.state, record.reason = "failed", "Interrupted before workflow completed"
                recorder.record = record
                checkpoint(output, execution)
                if not questions:
                    record.state, record.reason = (
                        "unsupported",
                        "No question binds to the frozen span",
                    )
                    record.seconds = clock() - started
                    continue
                questions = [
                    q.model_copy(
                        update={
                            "budget": q.budget.model_copy(
                                update={
                                    "max_retries": 0,
                                    "max_seconds": min(
                                        q.budget.max_seconds,
                                        prepared.max_seconds - (clock() - began),
                                    ),
                                }
                            )
                        }
                    )
                    for q in questions
                ]
                runs = RunStore(folder / f"{case.input_id}.sqlite")
                run_id = questions[0].run_id
                runs.create(
                    ReviewRun(
                        id=run_id,
                        snapshot_id=prepared.snapshot.id,
                        run_type=RunType.LIVE,
                        lifecycle=RunLifecycle.QUEUED,
                        created_at=datetime.now(UTC),
                        coverage=Coverage(total=len(questions), pending=len(questions)),
                    ),
                    questions,
                )
                try:
                    Workflow(
                        review,
                        runs,
                        run_id,
                        recorder,
                        folder / "guards.sqlite",
                        candidate.digest(prepared),
                        len(questions),
                    ).run()
                    record.questions = runs.questions(run_id)
                    record.state = (
                        "completed"
                        if all(q.status is QuestionStatus.ANSWERED for q in record.questions)
                        else "failed"
                    )
                    record.reason = (
                        "Production workflow completed"
                        if record.state == "completed"
                        else ("Workflow retains failed or unanswered questions")
                    )
                finally:
                    record.questions = runs.questions(run_id)
                    record.seconds = clock() - started
                    checkpoint(output, execution)
    except BaseException as error:
        refused = isinstance(error, PreflightRefused)
        execution.error = f"Development batch refused ({type(error).__name__})"
    finally:
        if server is not None:
            try:
                server.stop()
                if server.sampler is not None:
                    execution.observations.update(
                        peak_working_set_bytes=server.sampler.peak_working_set,
                        peak_private_bytes=server.sampler.peak_private,
                    )
            except Exception as error:
                refused = False
                execution.error = f"Model teardown failed ({type(error).__name__})"
        try:
            execution.machine_end = {"software_fixture": True} if fixture_model else machine_state()
        except Exception:
            execution.observations["machine_end"] = "unavailable"
        execution.finished_at = datetime.now(UTC)
        execution.elapsed_seconds = clock() - began
        execution.state = (
            "preflight_refused"
            if refused
            else "failed"
            if (
                execution.error
                or execution.elapsed_seconds > prepared.max_seconds
                or any(r.state != "completed" for r in execution.records)
            )
            else "completed"
        )
        checkpoint(output, execution)
    return execution


def result(
    prepared: candidate.Preparation, store: SnapshotStore, execution: Execution
) -> candidate.Result:
    candidate.check(prepared, store)
    run = Execution.model_validate(execution.model_dump())
    if run.preparation_sha256 != candidate.digest(prepared) or run.driver != identity():
        raise ValueError("Development driver/input identity changed")
    if run.finished_at is None or run.finished_at < run.started_at:
        raise ValueError("Only finished ordered executions can be accounted")
    if len({r.case_id for r in run.records}) != len(run.records) or (
        {r.case_id for r in run.records} != {c.id for c in prepared.cases}
    ):
        raise ValueError("Retain every selected case exactly once")
    if run.state == "completed" and (run.error or any(r.state != "completed" for r in run.records)):
        raise ValueError("Incomplete workflow cannot claim completion")
    rows = {r.case_id: r for r in run.records}
    # A valid caller citation alone cannot bind an arbitrary helper access.
    # Reconstruct authorization associations from frozen source, never saved labels.
    authorization = [
        c
        for c in prepared.cases
        if (c.family is Family.AUTHORIZATION or prepared.requirements is not None)
        and rows[c.id].state == "completed"
    ]
    if authorization:
        with (
            tempfile.TemporaryDirectory(prefix="tandir-account-") as name,
            frozen_review(prepared, store, Settings(data_dir=Path(name))) as (_, review),
        ):
            for case in authorization:
                canonical, _, _ = review.questions("run:" + case.input_id, [], [], tuple(Family))
                expected = focus_questions(review, case, canonical)
                actual = rows[case.id].questions

                def binding(q: Question) -> tuple[object, ...]:
                    return q.id, q.run_id, q.family, q.subject_ids, q.evidence

                if sorted(map(binding, actual), key=str) != sorted(map(binding, expected), key=str):
                    raise ValueError("Authorization question is not bound to the exact caller")
    validator = Validator(prepared.snapshot, store)
    cases = []
    requests = []
    for case in prepared.cases:
        record = rows[case.id]
        if record.packet_sha256 != case.input_id or any(
            a.case_id != case.id for a in record.requests
        ):
            raise ValueError("Record/requests do not bind to the exact case input")
        if record.state == "unrun" and (
            record.snapshot or record.questions or record.requests or record.seconds
        ):
            raise ValueError("Unrun case contains attempted evidence")
        if record.state != "unrun" and record.snapshot != prepared.snapshot:
            raise ValueError("Attempted case cites a different source snapshot")
        predictions = []
        if record.state == "completed":
            if (
                not record.questions
                or not record.requests
                or len({q.id for q in record.questions}) != len(record.questions)
                or any(
                    a.error or json.loads(a.raw_answer or "") != a.answer for a in record.requests
                )
            ):
                raise ValueError("Completed case requires exact raw usable workflow answers")
            for question in record.questions:
                if (
                    question.status is not QuestionStatus.ANSWERED
                    or not question.answer
                    or not overlaps(question, case)
                ):
                    raise ValueError("Completed question must bind to selected source")
                finding = Finding.model_validate(question.answer["finding"])
                data = question.answer["result"]
                judgment = (
                    ChallengeResult.model_validate(data)
                    if question.family is Family.AUTHORIZATION
                    else (
                        BoundaryResult.model_validate(data)
                        if question.family is Family.NEXTJS_EXPOSURE
                        else SinkResult.model_validate(data)
                    )
                )
                subject = (
                    judgment.site_id
                    if isinstance(judgment, ChallengeResult)
                    else (
                        judgment.entry_id
                        if isinstance(judgment, BoundaryResult)
                        else judgment.signal_id
                    )
                )
                if (
                    question.subject_ids != [subject]
                    or finding.conclusion != judgment.conclusion
                    or (
                        len(judgment.samples) != 3
                        or {s.seed for s in judgment.samples} != {42, 43, 44}
                    )
                ):
                    raise ValueError("Exact subject and three production judgments required")
                if any(
                    not any(
                        a.answer == sample.answer.model_dump(mode="json")
                        and a.body.get("seed") == sample.seed
                        for a in record.requests
                    )
                    for sample in judgment.samples
                ):
                    raise ValueError("Judgment lacks an exact raw answer/seed record")
                for guard in judgment.guards:
                    validator.confirm(guard, subject=guard.subject, object=guard.object)
                change = saved_change(question, finding, record.requests, prepared.snapshot, store)
                if (
                    finding.run_id != "run:" + case.input_id
                    or question.run_id != finding.run_id
                    or finding.question_ids != [question.id]
                    or finding.family is not question.family
                    or finding.runtime_verification is not RuntimeVerification.NOT_ATTEMPTED
                    or finding.probe_run_ids
                    or finding.policy_basis
                    != (
                        judgment.policies
                        if isinstance(judgment, ChallengeResult | BoundaryResult)
                        else []
                    )
                    or any(
                        p not in (prepared.requirements.policies if prepared.requirements else [])
                        for p in finding.policy_basis
                    )
                    or validator.finding(finding, guards=judgment.guards, change=change)
                    or any(validator.evidence(s) for s in question.evidence)
                ):
                    raise ValueError("Finding/source/runtime association failed")
                source = next(
                    (
                        e.span
                        for e in finding.exhibits
                        if e.span.path == case.source.path
                        and e.span.start_line <= case.source.end_line
                        and case.source.start_line <= e.span.end_line
                    ),
                    None,
                )
                if source is None or finding.family is not case.family:
                    raise ValueError("Finding lies outside selected development family/source")
                predictions.append(
                    Prediction(
                        family=finding.family,
                        path=source.path,
                        start_line=source.start_line,
                        end_line=source.end_line,
                        conclusion=finding.conclusion,
                    )
                )
        cases.append(
            candidate.CaseResult(
                case_id=case.id,
                state="completed"
                if record.state == "completed"
                else ("unrun" if record.state == "unrun" else "failed"),
                predictions=predictions,
                reason=record.reason,
            )
        )
        requests.extend(record.requests)
    preflight = run.observations.get("preflight")
    projected = candidate.Result(
        preparation_sha256=run.preparation_sha256,
        method="full_plumb",
        evidence_kind=run.evidence_kind,
        state=run.state,
        reason=run.error
        or (
            "Production Tandir development workflow completed"
            if run.state == "completed"
            else "Production Tandir development workflow retains failed or unrun cases"
        ),
        started_at=run.started_at,
        finished_at=run.finished_at,
        implementation=prepared.implementation,
        model=prepared.model,
        runtime=prepared.runtime,
        profile=prepared.profile,
        machine_start=run.machine_start,
        machine_end=run.machine_end,
        preflight=preflight if isinstance(preflight, dict) else None,
        judgments=3,
        requests=requests,
        cases=cases,
    )
    candidate.account(prepared, projected, store)
    return projected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for verb in ("run", "account"):
        command = commands.add_parser(verb)
        command.add_argument("directory", type=Path)
        if verb == "account":
            command.add_argument("execution", type=Path)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepared = read_record(args.directory / "preparation.json", candidate.Preparation)
        store = SnapshotStore(args.directory / "snapshots")
        if args.command == "run":
            execution = execute(prepared, store, args.output, Settings())
            print(execution.state)
            return 0 if execution.state == "completed" else 1
        execution = read_record(args.execution, Execution)
        projected = result(prepared, store, execution)
        candidate.write_new(args.output, candidate.account(prepared, projected, store))
        return 0
    except (ValueError, OSError) as error:
        print(f"Tandir development refused ({type(error).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

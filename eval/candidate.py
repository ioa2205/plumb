"""Offline development preparation and matched result accounting; never runs inference.

This is not the final frozen candidate. Sealed evaluation and execution adapters
remain deferred. Existing ground truth is evaluator-only, never model context.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256
from backend.contracts.code import ProjectSnapshot, SourceSpan
from backend.contracts.common import Contract, Family, Sha256
from backend.contracts.investigation import Conclusion
from backend.contracts.policies import FrozenPolicies
from backend.profiles import Profile
from backend.review import implementation_identity
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.baselines.common import report_dict
from eval.ground_truth import MANIFEST, Case, Kind, load, symbol_span
from eval.scoring.score import Prediction, Truth, score

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8 * 1024 * 1024
METHODS = (
    "full_plumb",
    "opengrep",
    "one_shot",
    "no_peer",
    "no_challenge",
    "no_grammar",
    "no_self_consistency",
    "no_verification",
)
Method = Literal[
    "full_plumb",
    "opengrep",
    "one_shot",
    "no_peer",
    "no_challenge",
    "no_grammar",
    "no_self_consistency",
    "no_verification",
]
LIMITS = [
    "Development preparation only; no final freeze, sealed test or model selection.",
    "M1.5b mutation corpus remains blocked; no mutation/test templates opened here.",
    "Matched execution adapters and five ablation implementations remain unrun/unprepared.",
    "Declared policy, injection-flip/transfer, proposal quality and resource measurements "
    "need their own matched inputs and actual acceptance; this source pack does not supply them.",
    "Runtime isolation, browser and clean-user gates remain open. Installed pins are not accuracy.",
]


def harness_identity() -> dict[str, str]:
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in (
            "eval/candidate.py",
            "eval/requirements.py",
            "eval/ground_truth/__init__.py",
            "eval/scoring/score.py",
            "eval/scoring/stats.py",
            "eval/baselines/common.py",
            "uv.lock",
            "pyproject.toml",
        )
    }


def digest(value: Contract) -> str:
    return hashlib.sha256(
        json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CaseInput(Contract):
    id: str = Field(pattern=r"^TANDIR-[A-Z0-9-]+$")
    # Opaque source input ID is separate from evaluator labels/expected answers.
    input_id: Sha256
    family: Family
    label: Literal["vulnerable", "safe"]
    source: SourceSpan
    file_sha256: Sha256
    cluster: str
    pair_id: str | None = None


class Preparation(Contract):
    schema_version: Literal[1] = 1
    scope: Literal["tandir_development_preparation"] = "tandir_development_preparation"
    final_candidate: Literal[False] = False
    created_at: AwareDatetime
    hypothesis: str = Field(min_length=1, max_length=1000)
    max_requests: int = Field(strict=True, gt=0, le=1000)
    max_seconds: int = Field(strict=True, gt=0, le=14400)
    stop_rule: Literal["stop_at_budget_or_first_process_memory_failure"] = (
        "stop_at_budget_or_first_process_memory_failure"
    )
    production_judgments: Literal[3] = 3
    snapshot: ProjectSnapshot
    cases: list[CaseInput] = Field(min_length=2, max_length=100)
    implementation: dict[str, Sha256]
    harness: dict[str, Sha256]
    model: dict[str, JsonValue]
    runtime: dict[str, JsonValue]
    profile: dict[str, JsonValue]
    ground_truth_sha256: Sha256
    split_manifest_sha256: Sha256
    preparation_machine: dict[str, JsonValue]
    requirements: FrozenPolicies | None = None
    requirements_sha256: Sha256 | None = None
    methods: tuple[Method, ...] = METHODS
    limitations: list[str] = Field(default_factory=lambda: list(LIMITS))

    @model_validator(mode="after")
    def _cases(self) -> Self:
        if (self.requirements is None) != (self.requirements_sha256 is None):
            raise ValueError("requirements and their manifest pin must travel together")
        if self.requirements is not None and self.requirements.snapshot_id != self.snapshot.id:
            raise ValueError("requirements belong to the exact frozen snapshot")
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("development case IDs must be unique")
        if any(c.source.snapshot_id != self.snapshot.id for c in self.cases):
            raise ValueError("cases require one common frozen source snapshot")
        pairs: dict[str, list[str]] = {}
        for case in self.cases:
            if case.pair_id:
                pairs.setdefault(case.pair_id, []).append(case.label)
        if any(sorted(labels) != ["safe", "vulnerable"] for labels in pairs.values()):
            raise ValueError("selected pairs must retain their protected counterparts")
        if self.methods != METHODS:
            raise ValueError("preparation must retain baselines and planned ablations")
        return self


class RequestRecord(Contract):
    case_id: str
    body: dict[str, JsonValue]
    answer: dict[str, JsonValue] | None = None
    raw_answer: str | None = Field(default=None, max_length=100000)
    error: str | None = Field(default=None, max_length=1000)
    prompt_tokens: int = Field(strict=True, ge=0)
    completion_tokens: int = Field(strict=True, ge=0)
    seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _attempt(self) -> Self:
        if (self.answer is None) == (self.error is None):
            raise ValueError("each request retains either its answer or failure")
        if self.answer is not None and self.raw_answer is None:
            raise ValueError("successful requests retain their raw answers")
        return self


class CaseResult(Contract):
    case_id: str
    state: Literal["completed", "failed", "unparseable", "unrun"]
    predictions: list[Prediction] = Field(default=[], max_length=20)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _unrun(self) -> Self:
        if self.state != "completed" and self.predictions:
            raise ValueError("failed/unrun cases cannot publish predictions")
        if any(p.start_line > p.end_line for p in self.predictions):
            raise ValueError("prediction ranges cannot run backwards")
        return self


class Result(Contract):
    schema_version: Literal[1] = 1
    preparation_sha256: Sha256
    method: Method
    evidence_kind: Literal["fresh_local", "saved_answer_replay", "software_fixture"]
    state: Literal["completed", "failed", "preflight_refused", "unrun"]
    reason: str = Field(min_length=1, max_length=1000)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    implementation: dict[str, Sha256]
    model: dict[str, JsonValue]
    runtime: dict[str, JsonValue]
    profile: dict[str, JsonValue]
    machine_start: dict[str, JsonValue]
    machine_end: dict[str, JsonValue]
    preflight: dict[str, JsonValue] | None = None
    judgments: int = Field(strict=True, ge=0, le=3)
    requests: list[RequestRecord] = Field(default=[], max_length=1000)
    cases: list[CaseResult] = Field(max_length=100)

    @model_validator(mode="after")
    def _status(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("result time runs backwards")
        if self.state == "completed" and any(c.state != "completed" for c in self.cases):
            raise ValueError("incomplete cases keep the result incomplete")
        if self.state in {"preflight_refused", "unrun"} and (
            self.requests or any(c.state != "unrun" for c in self.cases)
        ):
            raise ValueError("refused/unrun results cannot claim processed cases")
        if self.state == "preflight_refused" and (
            not self.preflight or self.preflight.get("ok") is not False
        ):
            raise ValueError("preflight refusal requires its actual failed observation")
        if (
            self.state == "completed"
            and self.evidence_kind == "fresh_local"
            and (
                not self.machine_start
                or not self.machine_end
                or (
                    self.method != "opengrep"
                    and (not self.preflight or self.preflight.get("ok") is not True)
                )
            )
        ):
            raise ValueError("fresh completed results require machine and passed preflight records")
        return self


def case_input(case: Case, snapshot: ProjectSnapshot, store: SnapshotStore) -> CaseInput:
    source = store.read(snapshot, case.path)
    if symbol_span(source.decode("utf-8"), case.path, case.symbol) != case.lines:
        raise ValueError("human-reviewed case span changed; update ground truth first")
    first, last = case.lines
    text = "\n".join(source.decode("utf-8").splitlines()[first - 1 : last])
    if any(anchor not in text for anchor in case.anchors) or (
        case.guard and case.guard not in text
    ):
        raise ValueError("frozen source disagrees with human-reviewed anchors/protection")
    span = SourceSpan(
        snapshot_id=snapshot.id,
        path=case.path,
        start_line=first,
        end_line=last,
        content_sha256=span_sha256(source, first, last),
    )
    return CaseInput(
        id=case.id,
        input_id=hashlib.sha256(f"{snapshot.id}:{case.path}:{first}:{last}".encode()).hexdigest(),
        family=case.family,
        label="vulnerable" if case.kind is Kind.FLAW else "safe",
        source=span,
        file_sha256=hashlib.sha256(source).hexdigest(),
        cluster=case.pair or case.id,
        pair_id=case.pair,
    )


def prepare(
    store: SnapshotStore,
    *,
    hypothesis: str,
    max_requests: int,
    max_seconds: int,
    case_ids: Sequence[str] = (),
    machine: dict[str, JsonValue],
    with_requirements: bool = False,
) -> Preparation:
    manifest = load()
    snapshot = take_snapshot(manifest.lab_root(), store)
    selected = [c for c in manifest.cases if not case_ids or c.id in case_ids]
    if case_ids and (
        len(set(case_ids)) != len(case_ids) or set(case_ids) != {c.id for c in selected}
    ):
        raise ValueError("select exact unique development case IDs")
    cases = [case_input(c, snapshot, store) for c in selected]
    profile = Profile()
    prepared = Preparation(
        created_at=datetime.now(UTC),
        hypothesis=hypothesis,
        max_requests=max_requests,
        max_seconds=max_seconds,
        snapshot=snapshot,
        cases=cases,
        implementation=implementation_identity(),
        harness=harness_identity(),
        model=load_model_pins().get(profile.model_id).model_dump(mode="json"),
        runtime=load_llama_cpp_pin().model_dump(mode="json"),
        profile=profile.identity(),
        ground_truth_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        split_manifest_sha256=hashlib.sha256(
            (ROOT / "eval/splits/manifest.json").read_bytes()
        ).hexdigest(),
        preparation_machine=machine,
    )
    if with_requirements:
        import tempfile

        from backend.settings import Settings
        from eval import requirements, tandir

        with (
            tempfile.TemporaryDirectory(prefix="tandir-requirements-") as name,
            tandir.frozen_review(prepared, store, Settings(data_dir=Path(name))) as (_, review),
        ):
            frozen = requirements.freeze(review, [c.source for c in cases], prepared.created_at)
        prepared = prepared.model_copy(
            update={"requirements": frozen, "requirements_sha256": requirements.pin()}
        )
    return prepared


def check(preparation: Preparation, store: SnapshotStore) -> None:
    p = Preparation.model_validate(preparation.model_dump())
    if p.requirements is not None:
        from eval.requirements import pin

        if p.requirements_sha256 != pin():
            raise ValueError("development requirements changed; prepare new inputs")
    if (
        p.implementation != implementation_identity()
        or p.harness != harness_identity()
        or store.load(p.snapshot.id) != p.snapshot
    ):
        raise ValueError("engine or snapshot metadata changed; prepare new inputs")
    if p.ground_truth_sha256 != hashlib.sha256(MANIFEST.read_bytes()).hexdigest() or (
        p.split_manifest_sha256
        != hashlib.sha256((ROOT / "eval/splits/manifest.json").read_bytes()).hexdigest()
    ):
        raise ValueError("evaluation manifests changed; prepare new inputs")
    profile = Profile()
    if (
        p.profile != profile.identity()
        or p.model != load_model_pins().get(profile.model_id).model_dump(mode="json")
        or p.runtime != load_llama_cpp_pin().model_dump(mode="json")
    ):
        raise ValueError("pinned model/runtime/profile changed; prepare new inputs")
    human_cases = {c.id: c for c in load().cases}
    for case in p.cases:
        if case.id not in human_cases or case != case_input(
            human_cases[case.id], p.snapshot, store
        ):
            raise ValueError("case labels/identities differ from human-reviewed ground truth")
        source = store.read(p.snapshot, case.source.path)
        if (
            hashlib.sha256(source).hexdigest() != case.file_sha256
            or case.source.end_line > len(source.splitlines())
            or span_sha256(source, case.source.start_line, case.source.end_line)
            != case.source.content_sha256
        ):
            raise ValueError("case source/citation changed")


def account(p: Preparation, result: Result, store: SnapshotStore) -> dict[str, JsonValue]:
    check(p, store)
    r = Result.model_validate(result.model_dump())
    if r.preparation_sha256 != digest(p) or any(
        getattr(r, k) != getattr(p, k) for k in ("implementation", "model", "runtime", "profile")
    ):
        raise ValueError("matched comparison requires identical frozen inputs and configuration")
    cases = {c.id: c for c in p.cases}
    if len(r.cases) != len(cases) or {c.case_id for c in r.cases} != set(cases):
        raise ValueError("results retain every selected case, including failed/unrun cases")
    expected_judgments = (
        0 if r.method == "opengrep" else 1 if r.method in {"one_shot", "no_self_consistency"} else 3
    )
    if r.judgments != expected_judgments:
        raise ValueError("method judgments disagree; production Plumb retains three")
    exceeded = (
        len(r.requests) > p.max_requests
        or sum(a.seconds for a in r.requests) > p.max_seconds
        or (r.finished_at - r.started_at).total_seconds() > p.max_seconds
    )
    if exceeded and r.state != "failed":
        raise ValueError("predeclared request/time budget exceeded")
    if any(a.case_id not in cases for a in r.requests):
        raise ValueError("request belongs to an unselected case")
    truths, predictions = [], []
    for row in r.cases:
        case = cases[row.case_id]
        span = case.source
        # A focused review's result belongs to its exact input. Adjacent functions
        # can share a file and fall inside the scorer's line tolerance; don't let
        # one case's report clear/credit/alarm another independently reviewed case.
        scoring_path = f"input-{case.input_id}/{span.path}"
        source = store.read(p.snapshot, span.path)
        if any(
            pred.path != span.path
            or pred.family != case.family
            or pred.end_line > len(source.splitlines())
            for pred in row.predictions
        ):
            raise ValueError("prediction is outside its selected family/frozen source")
        truths.append(
            Truth(
                id=case.id,
                family=case.family,
                label=case.label,
                path=scoring_path,
                start_line=span.start_line,
                end_line=span.end_line,
                template_family=case.cluster,
                pair_id=case.pair_id,
            )
        )
        if row.state == "completed":
            if r.method != "opengrep" and not any(
                a.case_id == row.case_id and a.answer is not None for a in r.requests
            ):
                raise ValueError("completed model case requires raw request/answer trace")
            predictions.extend(p.model_copy(update={"path": scoring_path}) for p in row.predictions)
        else:
            predictions.append(
                Prediction(
                    family=case.family,
                    path=scoring_path,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    conclusion=Conclusion.INCONCLUSIVE,
                )
            )
    # Partial results are accounted for, never published as an accuracy/acceptance pass.
    unprocessed: list[JsonValue] = [c.case_id for c in r.cases if c.state != "completed"]
    limitations: list[JsonValue] = [text for text in p.limitations]
    return {
        "evidence_kind": r.evidence_kind,
        "state": r.state,
        "release_acceptance": "unassessed",
        "metrics": report_dict(score(truths, predictions)),
        "budget_exceeded": exceeded,
        "unprocessed_cases": unprocessed,
        "limitations": limitations,
    }


def read(path: Path, model: type[Preparation] | type[Result]) -> Preparation | Result:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("evaluation record exceeds the size budget")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("evaluation record exceeds the size budget")
    return model.model_validate_json(raw)


def write_new(path: Path, value: Contract | dict[str, JsonValue]) -> None:
    data = value.model_dump(mode="json") if isinstance(value, Contract) else value
    text = json.dumps(data, indent=2) + "\n"
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("evaluation record exceeds the size budget")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="source-only development preparation")
    preparation.add_argument("--output", type=Path, required=True, help="new directory")
    preparation.add_argument("--hypothesis", required=True)
    preparation.add_argument("--max-requests", type=int, required=True)
    preparation.add_argument("--max-seconds", type=int, required=True)
    preparation.add_argument("--case", action="append", default=[])
    preparation.add_argument(
        "--with-requirements",
        action="store_true",
        help="freeze the separate current Tandir development policy pack",
    )
    for name in ("check", "account"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
        if name == "account":
            command.add_argument("result", type=Path)
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            from eval.bench.machine import machine_state

            args.output.mkdir(parents=True, exist_ok=False)
            store = SnapshotStore(args.output / "snapshots")
            p = prepare(
                store,
                hypothesis=args.hypothesis,
                max_requests=args.max_requests,
                max_seconds=args.max_seconds,
                case_ids=args.case,
                machine=machine_state(),
                with_requirements=args.with_requirements,
            )
            write_new(args.output / "preparation.json", p)
            print(
                f"Prepared {len(p.cases)} development cases; ID {digest(p)}. "
                "No inference/final freeze."
            )
        else:
            p = Preparation.model_validate(read(args.directory / "preparation.json", Preparation))
            store = SnapshotStore(args.directory / "snapshots")
            check(p, store)
            if args.command == "account":
                r = Result.model_validate(read(args.result, Result))
                write_new(args.output, account(p, r, store))
            print("Frozen development inputs checked. Quality/release gates remain unassessed.")
    except (OSError, ValueError):
        print(
            "Evaluation preparation refused. "
            "Check new output paths, exact case IDs, pins and budgets."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

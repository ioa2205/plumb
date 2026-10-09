"""Production workflow fixtures, exact packet accounting and refusal boundaries; no inference."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent.llm import JsonAnswer, ModelRequest, ModelUnavailable, Spend
from agent.tests.test_peers import PredicateStub
from backend.preflight import PreflightResult
from backend.settings import Settings
from eval import plumb
from eval.baselines import development as base
from eval.candidate import digest, write_new
from eval.mutation import development as corpus


@pytest.fixture(scope="module")
def prepared() -> base.Preparation:
    ids = {"v2_command_arguments/original", "v2_command_arguments/shell_input"}
    return base.prepare(
        [c for c in corpus.make_cases() if c.id in ids],
        hypothesis="Production pipeline fixture and exact matched accounting, no inference",
        max_attempts=2,
        max_seconds=60,
    )


class Judge:
    def __init__(self, *, invalid: bool = False, fail: bool = False) -> None:
        self.requests: list[ModelRequest] = []
        self.invalid, self.fail = invalid, fail

    def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
        self.requests.append(request)
        if self.fail:
            raise ModelUnavailable("Fixture process failed")
        data: dict[str, Any]
        if self.invalid:
            data = {"look": "execute_shell"}
        elif request.name == "gather":
            data = {"look": "enough"}
        elif request.name == "sink_safety":
            ids = re.findall(r"(L\d+).*?def ", request.user)
            data = {
                "mechanism": "parameterized" if "shell=False" in request.user else "none_found",
                "line_ids": ids[:1],
            }
        elif request.name == "guard_summary":
            data = PredicateStub().ask(request, spend).data
        elif request.name == "intentional_exception":
            data = {"reason": "none_found", "line_ids": []}
        elif request.name == "fix_sketch":
            # A refused proposal is a valid software observation, not a fixed claim.
            data = {
                "intent": "Fixture proposal",
                "edits": [],
                "probe": {
                    "parameter": None,
                    "denied": "unsafe_value",
                    "allowed": "safe_value",
                },
            }
        else:
            data = {"fields": []}
        spend.requests += 1
        spend.prompt_tokens += 10
        spend.completion_tokens += 5
        return JsonAnswer(data, json.dumps(data), 10, 5, 0)


@pytest.fixture(scope="module")
def completed(
    prepared: base.Preparation,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[plumb.Plan, plumb.Execution, Path, Judge]:
    folder = tmp_path_factory.mktemp("plumb-matched")
    plan = plumb.prepare(prepared, 40)
    judge = Judge()
    result = plumb.execute(
        prepared,
        plan,
        folder / "execution.json",
        Settings(data_dir=folder / "data"),
        fixture_model=judge,
    )
    return plan, result, folder, judge


def test_production_workflow_preserves_three_samples_and_exact_matched_inputs(
    prepared: base.Preparation,
    completed: tuple[plumb.Plan, plumb.Execution, Path, Judge],
) -> None:
    plan, result, folder, judge = completed
    assert result.state == "completed", result.model_dump()
    assert result.evidence_kind == "software_fixture" and result.error is None
    assert len(result.records) == len(prepared.cases)
    conclusions = []
    for record, packet in zip(result.records, base.check(prepared), strict=True):
        assert record.snapshot and record.packet_sha256 == packet.sha256
        assert {f.path: f.sha256 for f in record.snapshot.files} == {
            p: corpus.sha(s.encode()) for p, s in packet.sources.items()
        }
        assert record.state == "completed" and len(record.questions) == 1
        answer: Any = record.questions[0].answer
        assert answer and len(answer["result"]["samples"]) == 3
        assert [s["seed"] for s in answer["result"]["samples"]] == [42, 43, 44]
        assert answer["finding"]["runtime_verification"] == "not_attempted"
        conclusions.append(answer["finding"]["conclusion"])
    assert set(conclusions) == {"supported", "rejected"}
    metric: Any = plumb.account(prepared, plan, result)
    assert metric["release_acceptance"] == "unassessed"
    assert metric["metrics"]["recall"]["injection"]["successes"] == 1
    assert metric["metrics"]["paired_discrimination"]["successes"] == 1
    assert metric["unprocessed_cases"] == []
    assert not list((folder / "data/cache").glob("plumb-packet-*"))
    assert any(r.name == "fix_sketch" for r in judge.requests)
    for request in judge.requests:
        for case in prepared.cases:
            assert case.id not in request.user and f'"label": "{case.label}"' not in request.user
        assert "max_retries" not in request.body()


def test_shared_baseline_scoring_has_identical_denominators_and_pairs(
    prepared: base.Preparation,
    completed: tuple[plumb.Plan, plumb.Execution, Path, Judge],
) -> None:
    plan, result, _, _ = completed
    packets = base.check(prepared)
    saved = base.SavedRun(
        preparation_sha256=digest(prepared),
        method="one_shot",
        evidence_kind="software_fixture",
        state="completed",
        records=[
            base.SavedRecord(
                case_id=case.id,
                packet_sha256=packet.sha256,
                state="completed",
                raw=json.dumps(
                    {
                        "findings": []
                        if case.label == "safe"
                        else [
                            {
                                "path": packet.focus.path,
                                "family": "injection",
                                "start_line": packet.focus.start_line,
                                "end_line": packet.focus.end_line,
                                "explanation": "Evaluator-only fixture",
                            }
                        ]
                    }
                ),
                seconds=0,
                prompt_tokens=0,
                completion_tokens=0,
            )
            for case, packet in zip(prepared.cases, packets, strict=True)
        ],
    )
    assert (
        base.account(prepared, saved)["metrics"] == plumb.account(prepared, plan, result)["metrics"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "omitted",
        "duplicate",
        "digest",
        "packet",
        "snapshot",
        "raw",
        "judgment",
        "sample",
        "seed",
        "finding",
        "citation",
        "runtime",
        "budget",
        "unfinished",
        "unrun",
        "policy",
    ],
)
def test_corrupt_or_unmatched_evidence_cannot_be_accounted(
    prepared: base.Preparation,
    completed: tuple[plumb.Plan, plumb.Execution, Path, Judge],
    change: str,
) -> None:
    plan, result, _, _ = completed
    raw = result.model_dump(mode="json")
    record = raw["records"][0]
    question = record["questions"][0]
    finding = question["answer"]["finding"]
    if change == "omitted":
        raw["records"].pop()
    elif change == "duplicate":
        raw["records"][1] = record
    elif change == "digest":
        raw["plan_sha256"] = "a" * 64
    elif change == "packet":
        record["packet_sha256"] = "a" * 64
    elif change == "snapshot":
        record["snapshot"]["id"] = "a" * 64
    elif change == "raw":
        record["requests"][0]["raw_answer"] = "{}"
    elif change == "judgment":
        question["answer"]["result"]["conclusion"] = "inconclusive"
    elif change == "sample":
        question["answer"]["result"]["samples"].pop()
    elif change == "seed":
        for request in record["requests"]:
            request["body"]["seed"] = 99
    elif change == "finding":
        finding["question_ids"] = ["question:unrelated"]
    elif change == "citation":
        finding["exhibits"][0]["span"]["content_sha256"] = "a" * 64
    elif change == "runtime":
        finding["runtime_verification"] = "reproduced"
        finding["probe_run_ids"] = ["probe:fake"]
    elif change == "budget":
        raw["elapsed_seconds"] = prepared.max_seconds + 1
    elif change == "unfinished":
        raw["finished_at"] = None
    elif change == "unrun":
        raw["state"] = "unrun"
    else:
        record["packet_sha256"] = base.Packet.model_validate(
            {**base.packet(prepared.cases[0]).model_dump(), "allowed_client_fields": ["id"]}
        ).sha256
    with pytest.raises(ValueError):
        plumb.account(prepared, plan, plumb.Execution.model_validate(raw))


def test_drift_refuses_before_diagnostics_or_processes(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plumb.prepare(prepared, 20)
    monkeypatch.setattr(
        plumb.profiles, "create", lambda *_: pytest.fail("Process started before identity check")
    )
    monkeypatch.setattr(
        plumb, "machine_state", lambda: pytest.fail("Diagnostics before identity check")
    )
    for broken in (
        plan.model_copy(update={"pipeline": {}}),
        plan.model_copy(update={"preparation_sha256": "a" * 64}),
    ):
        with pytest.raises(ValueError):
            plumb.execute(
                prepared, broken, tmp_path / "run.json", Settings(data_dir=tmp_path / "data")
            )
    assert not (tmp_path / "run.json").exists()


def test_output_overwrite_refuses_before_work(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "run.json"
    output.write_bytes(b"owner file")
    monkeypatch.setattr(plumb, "machine_state", lambda: pytest.fail("Work before exclusive output"))
    with pytest.raises(FileExistsError):
        plumb.execute(
            prepared, plumb.prepare(prepared, 20), output, Settings(data_dir=tmp_path / "data")
        )
    assert output.read_bytes() == b"owner file"


def test_global_request_budget_stops_and_retains_failures_and_unrun_cases(
    prepared: base.Preparation,
    tmp_path: Path,
) -> None:
    plan = plumb.prepare(prepared, 1)
    judge = Judge()
    result = plumb.execute(
        prepared,
        plan,
        tmp_path / "run.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=judge,
    )
    assert result.state == "failed" and len(judge.requests) == 1
    assert [r.state for r in result.records] == ["failed", "unrun"]
    metric: Any = plumb.account(prepared, plan, result)
    assert len(metric["unprocessed_cases"]) == 2
    assert metric["metrics"]["recall"]["injection"]["trials"] == 1
    assert metric["metrics"]["recall"]["injection"]["successes"] == 0


@pytest.mark.parametrize(
    "mode", ["invalid_menu", "process_failure", "redaction", "interrupt", "clock"]
)
def test_refused_paths_do_not_become_safe_or_positive(
    prepared: base.Preparation,
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plumb.prepare(prepared, 30)
    judge = Judge(invalid=mode == "invalid_menu", fail=mode == "process_failure")
    if mode == "redaction":
        from backend.redaction import Redactor

        monkeypatch.setattr(
            plumb.Redactor, "configured", lambda: Redactor(secrets=("preview-tool",))
        )
    if mode == "interrupt":

        def stop(*_: object) -> JsonAnswer:
            raise KeyboardInterrupt

        monkeypatch.setattr(judge, "ask", stop)
    ticks = iter([0.0, 61.0, 62.0, 63.0, 64.0])
    result = plumb.execute(
        prepared,
        plan,
        tmp_path / "run.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=judge,
        **({"clock": lambda: next(ticks)} if mode == "clock" else {}),
    )
    assert result.state == "failed"
    if mode == "redaction":
        # Only the protected packet contains preview-tool. The unchanged second
        # packet may still run; the refused control must not count as cleared.
        assert result.records[0].state == "failed" and not result.records[0].requests
        assert all("preview-tool" not in request.user for request in judge.requests)
    else:
        assert not any(r.state == "completed" for r in result.records)
    metric: Any = plumb.account(prepared, plan, result)
    assert metric["metrics"]["paired_discrimination"]["successes"] == 0
    if mode == "process_failure":
        assert len(judge.requests) == 1 and result.records[1].state == "unrun"
    assert not list((tmp_path / "data/cache").glob("plumb-packet-*"))


def test_unrepresentable_client_allow_policy_remains_explicit_abstention(tmp_path: Path) -> None:
    cases = [
        c
        for c in corpus.make_cases()
        if c.id in {"v2_client_projection/original", "v2_client_projection/over_shared_props"}
    ]
    prepared = base.prepare(
        cases, hypothesis="Policy gap fixture only", max_attempts=2, max_seconds=60
    )
    plan = plumb.prepare(prepared, 20)
    judge = Judge()
    result = plumb.execute(
        prepared,
        plan,
        tmp_path / "run.json",
        Settings(data_dir=tmp_path / "data"),
        fixture_model=judge,
    )
    assert not judge.requests
    assert all(r.state == "unsupported" and "cannot yet" in r.reason for r in result.records)
    metric: Any = plumb.account(prepared, plan, result)
    assert len(metric["unprocessed_cases"]) == 2
    assert metric["metrics"]["recall"]["nextjs_exposure"]["trials"] == 1


class Server:
    startup_timeout = 120.0
    sampler = None
    load_seconds = 0.0

    def __init__(self, *, ok: bool, stop_error: bool = False) -> None:
        self.ok, self.stop_error = ok, stop_error
        self.starts = self.stops = 0
        self.client = httpx.Client(
            base_url="http://127.0.0.1", transport=httpx.MockTransport(self.reply)
        )

    def reply(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not JSON"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    def preflight(self) -> PreflightResult:
        return PreflightResult(self.ok, "fixture", 8192, 0, None, "Fixture memory gate")

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1
        self.client.close()
        if self.stop_error:
            raise RuntimeError("Fixture teardown failed")


@pytest.mark.parametrize("ok,stop_error", [(False, False), (True, False), (True, True)])
def test_actual_adapter_fake_transport_preflight_failure_raw_and_cleanup(
    prepared: base.Preparation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ok: bool,
    stop_error: bool,
) -> None:
    fake = Server(ok=ok, stop_error=stop_error)
    monkeypatch.setattr(plumb.profiles, "create", lambda *_: fake)
    monkeypatch.setattr(plumb, "machine_state", lambda: {"software_fixture": True})
    plan = plumb.prepare(prepared, 30)
    result = plumb.execute(
        prepared, plan, tmp_path / "run.json", Settings(data_dir=tmp_path / "data")
    )
    assert result.state == "failed" and fake.stops == 1
    observed_preflight: Any = result.observations["preflight"]
    assert fake.starts == int(ok) and observed_preflight["ok"] is ok
    if ok:
        assert result.records[0].requests[0].raw_answer == "not JSON"
    else:
        assert all(r.state == "unrun" and not r.requests for r in result.records)
    if stop_error:
        assert result.error and "teardown" in result.error
    plumb.account(prepared, plan, result)


def test_offline_cli_plan_check_and_saved_account(
    prepared: base.Preparation,
    completed: tuple[plumb.Plan, plumb.Execution, Path, Judge],
    tmp_path: Path,
) -> None:
    plan, result, _, _ = completed
    write_new(tmp_path / "preparation.json", prepared)
    write_new(tmp_path / "execution.json", result)
    p, plan_path = str(tmp_path / "preparation.json"), str(tmp_path / "plan.json")
    assert (
        plumb.main(["prepare", p, "--max-requests", str(plan.max_requests), "--output", plan_path])
        == 0
    )
    assert plumb.main(["check", p, plan_path]) == 0
    assert (
        plumb.main(
            [
                "account",
                p,
                plan_path,
                str(tmp_path / "execution.json"),
                "--output",
                str(tmp_path / "metrics.json"),
            ]
        )
        == 0
    )
    assert (
        json.loads((tmp_path / "metrics.json").read_bytes())["evidence_kind"] == "software_fixture"
    )


def test_cli_refuses_oversized_inputs_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(base, "MAX_BYTES", 10)
    path = tmp_path / "input.json"
    path.write_bytes(b" " * 11)
    with pytest.raises(ValueError, match="size budget"):
        plumb.read_record(path, plumb.Plan)
    assert (
        plumb.main(
            ["prepare", str(path), "--max-requests", "20", "--output", str(tmp_path / "out.json")]
        )
        == 1
    )
    assert not (tmp_path / "out.json").exists()


def test_packet_materialization_cannot_write_outside_root(tmp_path: Path) -> None:
    raw: Any = {
        "sources": {"../owner.py": "pass\n"},
        "focus": {"path": "../owner.py", "start_line": 1, "end_line": 1},
    }
    with pytest.raises(ValueError):
        plumb.snapshot(base.Packet.model_validate(raw), tmp_path)
    assert not (tmp_path.parent / "owner.py").exists()

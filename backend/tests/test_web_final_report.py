"""Final report state is transactional; no browser, target or model is started."""

from pathlib import Path

import pytest

from agent.closed import Attempt
from backend.contracts.web_journey import UserChoice, UserQuestion
from backend.web_journey import Halt, Journey
from backend.web_store import JourneyStore

from .test_web_object_identity import investigator


def offline(monkeypatch: pytest.MonkeyPatch, journey: Journey) -> None:
    for name in ("first_look", "ask_pending", "act", "judge"):
        monkeypatch.setattr(journey, name, lambda: None)


def test_final_report_and_saved_journey_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journey = investigator(tmp_path)
    offline(monkeypatch, journey)
    result = journey.run()
    assert result.status == "done"
    assert journey.step("report").state == "completed"
    saved = JourneyStore(journey.settings).load(result.journey_id)
    assert saved.status == result.status and saved.steps == result.steps
    text = Path(str(saved.report_path)).read_text(encoding="utf-8")
    assert "status **done**" in text
    assert (
        "Write the private report"
        in text.split("## What ran", 1)[1].split("## What could not run", 1)[0]
    )


@pytest.mark.parametrize("status", ["paused", "stopped", "failed"])
def test_intermediate_report_keeps_report_step_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    journey = investigator(tmp_path)
    offline(monkeypatch, journey)

    def stop() -> None:
        if status == "failed":
            raise RuntimeError("synthetic internal failure")
        raise Halt(status, "Explicit test stop")

    monkeypatch.setattr(journey, "act", stop)
    result = journey.run()
    assert result.status == status and journey.step("report").state == "planned"
    text = Path(str(result.report_path)).read_text(encoding="utf-8")
    assert f"status **{status}**" in text
    assert "Write the private report" in text.split("## What could not run", 1)[1]


def test_waiting_answer_is_reported_as_paused_without_completing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journey = investigator(tmp_path)
    offline(monkeypatch, journey)
    journey.update(
        waiting=[
            UserQuestion(
                subject="field:/app/login:name",
                question_type="field_meaning",
                text="Which approved value belongs here?",
                choices=[UserChoice(label="display_name", meaning="Approved account name")],
            )
        ]
    )
    result = journey.run()
    assert result.status == "paused" and journey.step("report").state == "planned"
    assert "status **paused**" in Path(str(result.report_path)).read_text(encoding="utf-8")


def test_failed_report_write_does_not_complete_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journey = investigator(tmp_path)
    offline(monkeypatch, journey)

    def fail(*_: object) -> Path:
        raise OSError("synthetic storage failure")

    monkeypatch.setattr("backend.web_report.write_report", fail)
    result = journey.run()
    assert result.status == "failed" and journey.step("report").state == "planned"
    assert result.report_path is None
    assert JourneyStore(journey.settings).load(result.journey_id).status == "failed"


def test_unqualified_type_spends_no_model_request(tmp_path: Path) -> None:
    journey = investigator(tmp_path)
    journey.count_model((Attempt(0, error="UnqualifiedQuestion"), Attempt(1, raw="ABSTAIN")))
    assert journey.view.spent.model_questions == 1

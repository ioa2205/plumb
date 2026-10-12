"""The real owned-fixture journey and the real chat questions, saved as they came out.

    uv run --locked --extra browser python -m eval.website_acceptance journey --output <new-folder>
    uv run --locked --extra browser python -m eval.website_acceptance chat --output <new-file> \\
        [--journey <journey-id>]

``journey`` exercises production plain-language scope setup against an inert
fixture name, binds only that accepted scope to the owned loopback runner, and
runs the pinned browser under the unchanged memory gates. It verifies a pause,
a no-answer resume, and an explicit reviewed synthetic-fixture answer.

``chat`` asks ordinary, creative, rewrite and mixed questions. Unqualified intent
uses explicit human choices, never fixture model routing. ``planning`` separately
requires a qualified real model choice from the saved approved fixture menu;
code/default ordering cannot satisfy it and no chosen action is executed.

Both save what actually happened, including refusals and unanswered questions.
Every result includes passed/unmet conditions. Unmet acceptance exits 2; driver
errors exit 1. These are workflow records, never fresh accuracy figures. Nothing
external is contacted. Profile selection is configurable with ``--profile``.
"""

import argparse
import hashlib
import json
import re
import shutil
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.asking import ModelAsker
from agent.closed import MenuItem, decide
from agent.intent import MESSAGE_INTENT
from agent.web_questions import NEXT_STEP, step_question
from backend.chat import Chats
from backend.contracts.chat import ChatAsk, ChatCreate, Intent
from backend.contracts.web import WebsiteScope, WebTarget, digest
from backend.contracts.web_journey import JourneyApprove, JourneyView
from backend.jobs import WorkerLock
from backend.local_model import local_model
from backend.model_qualification import intent_reason
from backend.redaction import Redactor
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin
from backend.web_cli import wizard
from backend.web_journey import new_journey
from backend.web_plan import approval_in_force, approve
from backend.web_run import run_journey
from backend.web_store import JourneyStore
from eval.bench.machine import machine_state
from verification.web_fixture import Fixture, launch

QUESTIONS: tuple[tuple[str, str, Intent], ...] = (
    ("ordinary", "What is SQL injection?", "general_question"),
    ("creative", "Write a short poem about autumn.", "creative_writing"),
    ("rewrite", "Make that poem shorter, keeping the same subject.", "creative_writing"),
)
MIXED = "What is broken access control, and what does this website test show about it?"
SETUP_ADDRESS = "https://chorsu-fixture.test"
RESUME_ANSWERS = {"field:/join:name": "display_name"}
ROOT = Path(__file__).resolve().parents[1]


def evaluated(record: dict[str, Any], conditions: dict[str, bool]) -> dict[str, Any]:
    """A finished process is not a passed acceptance. Missing checks stay unmet."""
    return {
        **record,
        "conditions": conditions,
        "unmet": [name for name, passed in conditions.items() if not passed],
        "passed": bool(conditions) and all(conditions.values()),
    }


def implementation() -> dict[str, str]:
    names = (
        "eval/website_acceptance.py",
        "backend/chat.py",
        "backend/web_cli.py",
        "backend/web_journey.py",
        "backend/web_run.py",
        "backend/web_plan.py",
        "backend/model_qualification.py",
        "agent/asking.py",
        "agent/closed.py",
        "agent/intent.py",
        "agent/web_questions.py",
        "verification/pins/chorsu.json",
    )
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def default_setup_inputs(fixture: Fixture) -> list[str]:
    """Reviewed synthetic answers to the real production wizard; never passwords."""
    scope = fixture.scope()
    values = ["/", "/", scope.purpose, scope.authority.granted_by, scope.authority.reference]
    for account in scope.accounts:
        values.extend(
            [
                account.account_id,
                "y" if account.provisioned else "n",
                account.role,
                account.label,
                account.username,
                account.contact_email or "",
            ]
        )
    values.extend(
        [
            "",
            "/signin",
            "/parcels",
            "Signed in as",
            "/join",
            "Creates one synthetic customer account in the fixture.",
            "n",
            "Signed in as",
        ]
    )
    for item, rule in zip(scope.objects, scope.rules, strict=True):
        values.extend(
            [item.path, item.owner_account_id, item.kind, item.marker or "", rule.statement]
        )
    values.extend(["", "1", "200", "yes", scope.name, ",".join(scope.public_values)])
    return values


def configured_scope(
    fixture: Fixture,
    inputs: list[str],
    write: Callable[[str], None],
) -> tuple[WebsiteScope, list[dict[str, str]]]:
    """Exercise production setup, then bind its inert placeholder to this owned fixture only."""
    if len(inputs) > 128 or any(
        not isinstance(value, str) or len(value) > 4096 for value in inputs
    ):
        raise ValueError("Setup inputs must be a bounded list of strings, without credentials")
    pending = iter(inputs)
    transcript: list[dict[str, str]] = []

    def read(prompt: str) -> str:
        try:
            value = next(pending)
        except StopIteration as error:
            raise ValueError("Setup inputs ended before the production wizard finished") from error
        if Redactor().text(value) != value:
            raise ValueError("Setup inputs must not contain credentials")
        transcript.append({"prompt": prompt, "answer": value})
        return value

    scope = wizard(read, write, address=SETUP_ADDRESS)
    if scope is None or scope.origin != SETUP_ADDRESS or next(pending, None) is not None:
        raise ValueError("The complete production scope setup was not accepted")
    owned = fixture.scope()
    by_username = {account.username: account for account in owned.accounts if account.provisioned}
    for account in scope.accounts:
        if account.provisioned:
            known = by_username.get(account.username)
            if known is None:
                raise ValueError(
                    "Only the owned fixture's provisioned synthetic accounts may sign in"
                )
            fixture.secrets.put(account.secret_ref, fixture.secrets.get(known.secret_ref))
    value = scope.model_dump()
    value.update(
        mode="owned_fixture",
        targets=[WebTarget(origin=fixture.origin, paths=scope.targets[0].paths)],
    )
    return WebsiteScope.model_validate(value), transcript


def journey_conditions(view: JourneyView, record: dict[str, Any]) -> dict[str, bool]:
    resumed = record.get("resume_with_answer", {})
    labels = [check for check in view.checks if check.path == "/api/parcels/4117/label"]
    parcels = [check for check in view.checks if check.path == "/api/parcels/4117"]
    report = (
        Path(str(view.report_path)).read_text(encoding="utf-8")
        if view.report_path and Path(str(view.report_path)).is_file()
        else ""
    )
    return {
        "production_scope_setup": record.get("scope_setup", {}).get("accepted") is True,
        "owned_scope_only": view.scope.mode == "owned_fixture",
        "pinned_javascript_browser_used": view.browser == "used",
        "journey_completed": view.status == "done" and not view.waiting,
        "provisioned_accounts_signed_in": all(
            account.state == "signed_in"
            for account in view.accounts
            if next(
                a for a in view.scope.accounts if a.account_id == account.account_id
            ).provisioned
        ),
        "approved_synthetic_signup_completed": any(
            account.state == "created" for account in view.accounts
        ),
        "resume_without_answer_kept_waiting": record.get("resume_without_answer", {}).get("status")
        == "paused",
        "explicit_answer_resumed_work": resumed.get("status") == "done"
        and any(
            decision.subject in RESUME_ANSWERS
            and decision.rung == "user"
            and decision.value == RESUME_ANSWERS[decision.subject]
            for decision in view.decisions
        ),
        "comparisons_completed": bool(view.checks)
        and all(check.state == "completed" for check in view.checks),
        "owned_label_control_matches_variant": bool(labels)
        and all(
            check.comparison == ("candidate" if record["variant"] == "open" else "protected")
            for check in labels
        ),
        "markerless_object_not_promoted": bool(parcels)
        and all(
            check.comparison == ("inconclusive" if record["variant"] == "open" else "protected")
            for check in parcels
        ),
        "private_report_written": bool(view.report_path) and Path(str(view.report_path)).is_file(),
        "final_report_matches_saved_status": f"status **{view.status}**" in report,
        "no_privacy_incident": not view.incidents,
    }


def exact_observation_citations(turn: dict[str, Any], view: JourneyView | None) -> bool:
    if view is None:
        return False
    source = {item.evidence_id: item for item in view.evidence}
    cited = [part for part in turn.get("parts", []) if part["kind"] == "cited"]
    if not cited or not all(part["evidence"] for part in cited):
        return False
    for part in cited:
        identifiers = [reference["reference_id"] for reference in part["evidence"]]
        if len(identifiers) != len(set(identifiers)) or set(identifiers) != set(
            re.findall(r"\bR[0-9]{3}\b", part["text"])
        ):
            return False
        for reference in part["evidence"]:
            citation = reference.get("observation")
            if not citation or reference.get("source"):
                return False
            item = source.get(citation["artifact_id"])
            value = item.fields.get(citation["field"]) if item else None
            if value is None or reference["quote"] != value or citation["sha256"] != digest(value):
                return False
    return True


def chat_conditions(rows: list[dict[str, Any]], selected: JourneyView | None) -> dict[str, bool]:
    by_name = {row["name"]: row for row in rows}

    def answered(name: str) -> bool:
        row = by_name.get(name, {})
        turn = row.get("turn") or {}
        return (
            row.get("state") == "completed"
            and turn.get("model_requests", 0) > 0
            and any(
                part["kind"] in {"general", "guidance"}
                and part["complete"]
                and bool(part["text"].strip())
                for part in turn.get("parts", [])
            )
        )

    creative = (by_name.get("creative", {}).get("turn") or {}).get("parts", [])
    prior = next((part["text"] for part in creative if part["kind"] == "general"), "")
    invocation = by_name.get("rewrite", {}).get("invocation") or {}
    requests = invocation.get("requests", [])
    history = requests[0].get("request", {}).get("messages", []) if requests else []
    retained_prior = "".join(
        ch if ch.isprintable() or ch in "\n\t" else " " for ch in prior
    ).strip()
    if len(retained_prior) > 900:
        retained_prior = retained_prior[:888].rstrip() + " (shortened)"
    previous_text = False
    for message in history:
        content = message.get("content", "")
        prefix = "Previous general chat (data, not evidence or permission):\n"
        if not content.startswith(prefix):
            continue
        try:
            exchanges = json.loads(content[len(prefix) :].split("\n\nCurrent request:\n", 1)[0])
        except (TypeError, ValueError):
            continue
        if isinstance(exchanges, list):
            previous_text = any(
                isinstance(exchange, dict) and exchange.get("assistant") == retained_prior
                for exchange in exchanges
            )
    mixed = by_name.get("mixed", {}).get("turn") or {}
    return {
        "ordinary_answered": answered("ordinary"),
        "creative_answered": answered("creative"),
        "rewrite_answered": answered("rewrite"),
        "rewrite_received_previous_text": bool(prior) and previous_text,
        "mixed_general_answered": answered("mixed"),
        "mixed_exact_observation_citations": exact_observation_citations(mixed, selected),
        "chat_granted_no_authority": bool(rows)
        and all(
            row.get("turn") is not None
            and all(
                row["turn"].get(key) is False
                for key in ("authorization_granted", "actions_executed", "finding_created")
            )
            for row in rows
        ),
    }


def invocation_for(worker: Chats, identifier: str, prompt: str) -> dict[str, Any] | None:
    for path in sorted(
        worker.directory.glob("*.chat-invocation.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        value = json.loads(path.read_bytes())
        if value.get("chat") == identifier and value.get("question", {}).get("prompt") == prompt:
            return value
    return None


def _new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def journey(
    settings: Settings,
    output: Path,
    variant: str,
    use_model: bool,
    *,
    profile: str = "auto",
    setup_inputs: Path | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    record: dict[str, Any] = {
        "kind": "website_journey_acceptance",
        "started": datetime.now(UTC).isoformat(),
        "variant": variant,
        "use_model": use_model,
        "profile_requested": profile,
        "implementation": implementation(),
        "approval_source": "Owner selected owned-fixture acceptance; no external permission.",
        "machine_start": machine_state(),
        "llama_cpp": load_llama_cpp_pin().release,
    }
    with launch(variant, settings) as fixture:  # ty: ignore[invalid-argument-type]
        if setup_inputs is not None:
            if setup_inputs.stat().st_size > 64 * 1024:
                raise ValueError("Setup inputs exceed their bound")
            inputs = json.loads(setup_inputs.read_bytes())
            if not isinstance(inputs, list):
                raise ValueError("Setup inputs must be a JSON list")
        else:
            inputs = default_setup_inputs(fixture)
        scope, transcript = configured_scope(fixture, inputs, lambda _: None)
        record["scope_setup"] = {
            "accepted": True,
            "source": str(setup_inputs) if setup_inputs else "reviewed fixture defaults",
            "transcript": transcript,
            "inert_input_origin": SETUP_ADDRESS,
            "owned_runner_origin": scope.origin,
            "scope_sha256": scope.sha256,
        }
        _new(output / "scope.json", scope.model_dump(mode="json"))
        planned = new_journey(settings, scope, profile)
        approved = approve(
            planned,
            JourneyApprove(
                plan_sha256=planned.plan_sha256,
                approved_by="Acceptance driver (owner-selected build)",
                reviewed_plan=True,
            ),
        )
        JourneyStore(settings).save(approved)
        phases: list[str] = []
        view, notes = run_journey(
            settings,
            approved.journey_id,
            secrets=fixture.secrets,
            fixture=fixture,
            use_model=use_model,
            profile=profile,
            progress=lambda kind, state: phases.append(f"{kind}:{state}"),
        )
        record["first_run"] = {"status": view.status, "waiting": len(view.waiting), "notes": notes}
        if view.status == "paused" and view.waiting:
            # Resume once without an answer: the journey must hold its place, not guess.
            view, more = run_journey(
                settings,
                approved.journey_id,
                secrets=fixture.secrets,
                fixture=fixture,
                use_model=False,
                profile=profile,
            )
            record["resume_without_answer"] = {"status": view.status, "notes": more}
            waiting = {
                asked.subject: {choice.label for choice in asked.choices} for asked in view.waiting
            }
            answers = {
                subject: value
                for subject, value in RESUME_ANSWERS.items()
                if value in waiting.get(subject, set())
            }
            if answers:
                view, more = run_journey(
                    settings,
                    approved.journey_id,
                    secrets=fixture.secrets,
                    fixture=fixture,
                    use_model=use_model,
                    profile=profile,
                    answers=answers,
                    progress=lambda kind, state: phases.append(f"{kind}:{state}"),
                )
                record["resume_with_answer"] = {
                    "status": view.status,
                    "answers": answers,
                    "notes": more,
                    "basis": "Reviewed synthetic-fixture user answer; never a model answer.",
                }
    record.update(
        {
            "finished": datetime.now(UTC).isoformat(),
            "seconds": round(time.perf_counter() - started, 2),
            "journey_id": view.journey_id,
            "status": view.status,
            "stop_reason": view.stop_reason,
            "steps": {step.step_id: step.state for step in view.steps},
            "accounts": {account.account_id: account.state for account in view.accounts},
            "checks": {check.check_id: [check.comparison, check.judged] for check in view.checks},
            "findings": [
                [item.finding_id, item.conclusion, item.explanation_source]
                for item in view.findings
            ],
            "spent": view.spent.model_dump(mode="json"),
            "browser": view.browser,
            "blocked_requests": sum(row.count for row in view.blocked),
            "model_progress": phases,
            "machine_end": machine_state(),
        }
    )
    _new(output / "journey.json", json.loads(view.model_dump_json()))
    if view.report_path:
        shutil.copyfile(view.report_path, output / "report.md")
    record = evaluated(record, journey_conditions(view, record))
    _new(output / "acceptance.json", record)
    return record


def chat(
    settings: Settings,
    output: Path,
    journey_id: str | None,
    *,
    profile: str = "auto",
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("The output file already exists")
    started = time.perf_counter()
    worker = Chats(settings, hold_model=True)
    turns: list[dict[str, Any]] = []
    selected = JourneyStore(settings).load(journey_id) if journey_id else None
    if selected is not None and selected.scope.mode != "owned_fixture":
        raise ValueError("Acceptance chat selects only an owned-fixture journey")
    cleanup_completed = False
    try:
        view = worker.new()
        asked = list(QUESTIONS)
        for index, (name, prompt, chosen) in enumerate(
            [*asked, ("mixed", MIXED, "general_and_result")] if journey_id else asked
        ):
            if name == "mixed":
                worker.release_model()  # selecting a target reads storage under the same lock
                view = worker.select(
                    view.chat_id, ChatCreate(target_kind="website", target_id=journey_id)
                )
            fallback = intent_reason(settings, profile, MESSAGE_INTENT)
            choice = chosen if fallback else None
            worker.start(
                view.chat_id,
                ChatAsk(prompt=prompt, max_seconds=300, profile=profile, choice=choice),
            )
            view = worker.wait(view.chat_id, 400)
            turn = view.turns[-1] if len(view.turns) > index else None
            turns.append(
                {
                    "name": name,
                    "prompt": prompt,
                    "state": view.state,
                    "message": view.message,
                    "turn": turn.model_dump(mode="json") if turn is not None else None,
                    "explicit_user_choice": choice,
                    "choice_reason": fallback,
                    "invocation": invocation_for(worker, view.chat_id, prompt),
                }
            )
            print(f"  {name}: {view.state}", flush=True)
    finally:
        worker.close()
        cleanup_completed = True
    record = {
        "kind": "chat_acceptance",
        "at": datetime.now(UTC).isoformat(),
        "seconds": round(time.perf_counter() - started, 2),
        "journey_id": journey_id,
        "profile_requested": profile,
        "implementation": implementation(),
        "declared_budget": {"max_requests": 12, "max_seconds": 1200},
        "cleanup_completed": cleanup_completed,
        "turns": turns,
        "machine_end": machine_state(),
    }
    record = evaluated(
        record, {**chat_conditions(turns, selected), "model_cleanup_completed": cleanup_completed}
    )
    _new(output, record)
    return record


def planning_conditions(record: dict[str, Any]) -> dict[str, bool]:
    decision = record.get("decision") or {}
    return {
        "owned_approved_menu": record.get("owned_approved_menu") is True,
        "type_qualified_for_exact_pins": record.get("qualification_reason") is None,
        "actual_model_menu_choice": decision.get("rung") in {"model", "model_reordered"}
        and decision.get("value") in {item["key"] for item in record.get("menu", [])}
        and any(
            attempt.get("raw") and attempt.get("completion_tokens", 0) > 0
            for attempt in decision.get("attempts", [])
        ),
        "owned_model_stopped": record.get("manifest", {}).get("model_stopped") is True,
        "no_action_executed": record.get("executes_actions") is False,
    }


def planning(
    settings: Settings,
    output: Path,
    journey_id: str,
    *,
    profile: str = "auto",
) -> dict[str, Any]:
    """Choose from real approved owned-fixture checks; never execute the selected action."""
    if output.exists():
        raise ValueError("The output file already exists")
    view = JourneyStore(settings).load(journey_id)
    if view.scope.mode != "owned_fixture" or approval_in_force(view) is not None:
        raise ValueError("Planning acceptance requires an in-force approved owned-fixture scope")
    approved = set(view.approval.approved_step_ids) if view.approval else set()
    signed = {
        account.account_id for account in view.accounts if account.state in {"signed_in", "created"}
    }
    objects = {item.object_id: item for item in view.scope.objects}
    items = [
        MenuItem(
            step.step_id,
            step.summary[:200],
            step.account_id in signed and objects[str(step.object_id)].owner_account_id in signed,
        )
        for step in view.plan.steps
        if step.stage == "check" and step.step_id in approved
    ]
    if not 2 <= len(items) <= 6 or not all(item.ready for item in items):
        raise ValueError(
            "Planning needs two to six approved checks with signed-in synthetic accounts"
        )
    question = step_question(view.scope.purpose, items)
    reason = intent_reason(settings, profile, NEXT_STEP)
    manifest: dict[str, Any] = {}
    record: dict[str, Any] = {
        "kind": "website_planning_acceptance",
        "at": datetime.now(UTC).isoformat(),
        "journey_id": journey_id,
        "plan_sha256": view.plan_sha256,
        "profile_requested": profile,
        "implementation": implementation(),
        "declared_budget": {"max_requests": 2, "max_seconds": 180},
        "owned_approved_menu": True,
        "qualification_reason": reason,
        "menu": [{"key": item.key, "text": item.text, "ready": item.ready} for item in items],
        "request": question.request().body(),
        "executes_actions": False,
    }
    started = time.perf_counter()
    deadline = started + 180
    decision = decide(question, None)
    if reason is None:
        try:
            with (
                WorkerLock(settings.cache_dir / "review.lock"),
                local_model(
                    settings,
                    "website-planning-acceptance",
                    profile,
                    cancel=threading.Event(),
                    deadline=lambda: deadline,
                    manifest=manifest,
                ) as loaded,
            ):
                decision = decide(
                    question,
                    ModelAsker(loaded.adapter, profile=loaded.profile.id, seconds_per_question=90),
                )
        except (OSError, ValueError, RuntimeError) as error:
            record["error"] = type(error).__name__
    record.update(
        decision=decision.record(),
        manifest=manifest,
        seconds=round(time.perf_counter() - started, 3),
        machine_end=machine_state(),
    )
    record = evaluated(record, planning_conditions(record))
    _new(output, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("journey")
    one.add_argument("--output", type=Path, required=True)
    one.add_argument("--variant", choices=["open", "defended"], default="open")
    one.add_argument("--no-model", action="store_true")
    one.add_argument("--profile", default="auto")
    one.add_argument(
        "--setup-inputs",
        type=Path,
        help="Bounded JSON list of answers to the production scope wizard; owned fixture only",
    )
    two = commands.add_parser("chat")
    two.add_argument("--output", type=Path, required=True)
    two.add_argument("--journey")
    two.add_argument("--profile", default="auto")
    three = commands.add_parser("planning")
    three.add_argument("--output", type=Path, required=True)
    three.add_argument("--journey", required=True)
    three.add_argument("--profile", default="auto")
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.command == "journey":
            record = journey(
                settings,
                args.output,
                args.variant,
                not args.no_model,
                profile=args.profile,
                setup_inputs=args.setup_inputs,
            )
            print(
                f"Journey {record['status']} in {record['seconds']:.0f} s: "
                f"{record['spent']['requests']} requests, "
                f"{record['spent']['model_questions']} model questions, "
                f"findings {record['findings']}"
            )
        elif args.command == "chat":
            record = chat(settings, args.output, args.journey, profile=args.profile)
            print(f"{len(record['turns'])} chat turns in {record['seconds']:.0f} s")
        else:
            record = planning(settings, args.output, args.journey, profile=args.profile)
            print(f"Planning rung: {record['decision']['rung']}; no action executed.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Acceptance driver stopped: {error}")
        failed = evaluated(
            {
                "kind": "website_acceptance_driver_error",
                "command": args.command,
                "at": datetime.now(UTC).isoformat(),
                "error": type(error).__name__,
                "reason": Redactor.configured(settings).text(str(error)),
                "implementation": implementation(),
            },
            {"driver_completed": False},
        )
        destination = args.output / "acceptance.json" if args.command == "journey" else args.output
        if not destination.exists():
            _new(destination, failed)
        return 1
    print("Passed." if record["passed"] else "Unmet: " + ", ".join(record["unmet"]))
    return 0 if record["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

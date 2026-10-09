"""Plumb's local review CLI. No target code is executed."""

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.llm import JsonAnswer, ModelAdapter, ModelRequest, Spend
from analysis.overview import overview
from analysis.overview import summary as overview_summary
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.console import review_interrupts
from backend.contracts.common import Family
from backend.contracts.investigation import QuestionStatus
from backend.contracts.runs import ModelRef, ReviewRun, RunLifecycle, RunType, Toolchain
from backend.jobs import WorkerLock
from backend.preflight import PreflightResult
from backend.profiles import REGISTRY, create, doctor, select, validate_resume
from backend.review import Review, Workflow, export, implementation_identity, write_json
from backend.run_store import RunStore
from backend.saved_reports import show, summary
from backend.settings import Settings
from backend.setup.pins import load_llama_cpp_pin, load_model_pins
from eval.bench.machine import machine_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    from backend.setup.__main__ import add_arguments, execute

    add_arguments(commands.add_parser("setup", help="Preview or install Plumb's own prerequisites"))
    web = commands.add_parser("web", help="Open the local workbench; no model is loaded")
    web.add_argument(
        "--no-open", action="store_true", help="Print the link without opening a browser"
    )
    diagnostic = commands.add_parser("doctor", help="Read-only hardware, assets and profile checks")
    diagnostic.add_argument("--json", action="store_true", help="Print full diagnostic JSON")
    report_command = commands.add_parser("report", help="Read a saved report without analysis")
    report_command.add_argument("run_id")
    report_command.add_argument("--open", action="store_true", help="Request the default browser")
    replay_command = commands.add_parser(
        "replay", help="Verify the pinned Tandir receipt fix for a matching completed review"
    )
    replay_command.add_argument("run_id")
    replay_command.add_argument("--finding", required=True, help="Finding ID or display ID (F-02)")
    inspect = commands.add_parser("inspect", help="Understand an authorized folder without a model")
    inspect.add_argument("folder", type=Path)
    review = commands.add_parser("review", help="Review an authorized local folder")
    review.add_argument("folder", type=Path)
    review.add_argument("--resource", action="append", default=[], help="Narrow to a resource name")
    review.add_argument(
        "--route", action="append", default=[], help="Narrow to an exact discovered route"
    )
    review.add_argument("--guard-cache", type=Path)
    review.add_argument(
        "--family",
        action="append",
        choices=[f.value for f in Family],
        help="Select investigation families; default authorization",
    )
    resume = commands.add_parser("resume", help="Continue the original frozen snapshot")
    resume.add_argument("run_id")
    policy = commands.add_parser(
        "policy", help="Declare a requirement on frozen access IDs; no model"
    )
    policy.add_argument("run_id")
    policy.add_argument("--snapshot", required=True)
    policy.add_argument("--site", action="append", required=True)
    policy.add_argument("--guard", choices=["authenticated", "owner", "tenant", "role", "none"])
    policy.add_argument("--required-role", help="exact role required by a --guard role policy")
    policy.add_argument("--forbid-field", action="append", default=[])
    policy.add_argument("--statement", required=True)
    policy.add_argument("--author", required=True)
    for command in (review, resume):
        command.add_argument(
            "--open-report",
            action="store_true",
            help="Request the browser after stopping the model",
        )
        command.add_argument(
            "--profile",
            choices=["auto", *REGISTRY],
            help="Measured profile; resume retains its identity",
        )
        command.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Questions per invocation; remaining work pauses (default 5)",
        )
    args = parser.parse_args(argv)
    if args.command in {"review", "resume"} and args.limit < 1:
        parser.error("--limit must be positive")
    if args.command == "setup":
        return execute(args)
    if args.command == "web":
        from backend.serve import main as serve

        return serve(open_browser=not args.no_open)
    try:
        settings = Settings()
    except (OSError, ValueError):
        print(
            "Cannot read Plumb settings. Check PLUMB_* values or run plumb setup --data-dir "
            "<absolute-external-folder>. Existing preferences were preserved."
        )
        return 1
    if args.command == "replay":
        from verification.report_replay import attach

        return attach(settings, args.run_id, args.finding)
    if args.command == "report":
        try:
            return show(settings, args.run_id, open_browser=args.open)
        except (OSError, ValueError) as error:
            print(
                f"Saved report refused ({type(error).__name__}). "
                "Check the review ID, report files, evidence store and redaction settings."
            )
            return 1
    if args.command == "doctor":
        from backend.redaction import Redactor

        try:
            report = doctor(settings)
            if args.json:
                print(json.dumps(Redactor.configured().strings(report), indent=2))
            else:
                profile = report["profiles"][0]
                host = report["inventory"]
                print(
                    Redactor.configured().text(
                        f"{host['os']} / {host['architecture']} | CPU: {host['cpu'] or 'unknown'}\n"
                        f"Available RAM: {host['memory']['available_bytes']} bytes\n"
                        f"Dedicated MX350 VRAM: {profile['dedicated_free_bytes']} bytes\n"
                        f"Data-volume free disk: {host['disk_free_bytes']} bytes\n"
                        f"Profile: {profile['id']} | ready: {profile['ready']}\n"
                        f"Verified model/runtime: {profile['model_verified']}/"
                        f"{profile['runtime_verified']}\n"
                        f"{report['memory_note']}\n{profile['evaluated_capability']}\n"
                        + "\n".join(report["messages"])
                        + "\nFull inventory and pinned download previews: plumb doctor --json"
                    )
                )
            return 0 if report["selection_ready"] else 2
        except Exception as error:
            print(Redactor.configured().text(f"Doctor failed: {error}"))
            return 1
    if args.command == "policy":
        from backend.contracts.policies import PolicyInput
        from backend.project_reads import ProjectReads
        from backend.redaction import Redactor

        try:
            saved = ProjectReads(settings).declare(
                args.run_id,
                PolicyInput(
                    snapshot_id=args.snapshot,
                    site_ids=args.site,
                    required_guard=args.guard,
                    required_role=args.required_role,
                    forbidden_fields=args.forbid_field,
                    statement=args.statement,
                    author=args.author,
                ),
            )
            print(
                json.dumps(Redactor.configured().strings(saved.model_dump(mode="json")), indent=2)
            )
            return 0
        except (OSError, ValueError) as error:
            print(Redactor.configured().text(f"Policy declaration failed: {error}"))
            return 1
    with review_interrupts():
        return execute_review(args, settings)


def execute_review(
    args: argparse.Namespace,
    settings: Settings,
    *,
    requested_id: str | None = None,
    expected_snapshot: str | None = None,
    expected_source: dict[str, object] | None = None,
    ready: Callable[[str], None] | None = None,
    failed: Callable[[Exception], None] | None = None,
) -> int:
    """Shared CLI/browser workflow. The caller never supplies a model or handler."""
    runs = RunStore(settings.cache_dir / "runs.sqlite")
    context = None
    server = None
    directory = None
    workflow: Workflow | None = None
    manifest: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "requests": [],
        "preflights": [],
    }
    config: dict[str, Any]
    try:
        # Covers setup and inference, before Engine acquires the existing database worker lock.
        with WorkerLock(settings.cache_dir / "review.lock"):
            if args.command in {"review", "inspect"}:
                root = args.folder.resolve(strict=True)
                if expected_source is not None:
                    from backend.source_binding import root_for

                    if root_for(settings, expected_source) != root:
                        raise ValueError("original inspected folder changed")
                if settings.data_dir.resolve().is_relative_to(root):
                    raise ValueError("PLUMB_DATA_DIR must be outside the analyzed folder")
                if getattr(args, "guard_cache", None) and args.guard_cache.resolve().is_relative_to(
                    root
                ):
                    raise ValueError("Guard cache must be outside the analyzed folder")
                snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
                if expected_snapshot is not None and snapshot.id != expected_snapshot:
                    raise ValueError("Source changed after inspection; inspect it again")
                run_id = requested_id or "review-" + uuid4().hex
                directory = settings.data_dir / "reviews" / run_id
                directory.mkdir(parents=True)
                context = Review(settings, snapshot.id)
                from backend.redaction import Redactor

                result = overview(context.snapshot, context.map, context.access, context.store)
                write_json(
                    directory / "overview.json",
                    Redactor.configured().strings(result.model_dump(mode="json")),
                )
                print(Redactor.configured().text(overview_summary(result)), flush=True)
                if args.command == "inspect":
                    manifest.update({"snapshot_id": snapshot.id, "model_loaded": False})
                    print(f"Saved {directory / 'overview.json'}", flush=True)
                    return 0
                context.freeze_policies()
                policies_path = directory / "policies.json"
                write_json(policies_path, context.policies.model_dump(mode="json"))
                questions, coverage, exclusions = context.questions(
                    run_id,
                    args.resource,
                    args.route,
                    tuple(Family(f) for f in (args.family or [Family.AUTHORIZATION.value])),
                )
                if not questions:
                    raise ValueError("No supported source checks match this scope")
                selected_profile = select(settings, args.profile or "auto")
                server = create(settings, run_id, selected_profile)
                from backend.scheduling import order_questions, prepare

                model_pin = load_model_pins().get(selected_profile.model_id).model_dump(mode="json")
                launch = server.config.argv(0, "<per-launch key>")
                identity = (
                    json.dumps(selected_profile.identity(), sort_keys=True)
                    + json.dumps(model_pin, sort_keys=True)
                    + json.dumps(launch)
                )
                guard_cache = args.guard_cache or settings.cache_dir / "guards" / "summaries.sqlite"
                print(
                    "Preparing the queue from frozen source and cached guard evidence...",
                    flush=True,
                )
                context.preparation = prepare(context, run_id, guard_cache, identity)
                questions = order_questions(context, questions)
                preparation_path = directory / "scheduling.json"
                write_json(preparation_path, context.preparation.model_dump(mode="json"))
                config = {
                    "policies_sha256": hashlib.sha256(policies_path.read_bytes()).hexdigest(),
                    "snapshot_id": snapshot.id,
                    "source": {
                        "folder": str(root),
                        "device": root.stat().st_dev,
                        "inode": root.stat().st_ino,
                    },
                    "guard_cache": str(guard_cache),
                    "scheduling_sha256": hashlib.sha256(preparation_path.read_bytes()).hexdigest(),
                    "scheduling_limits": context.scheduling_limits,
                    "implementation": implementation_identity(),
                    "resources": args.resource,
                    "routes": args.route,
                    "families": args.family or [Family.AUTHORIZATION.value],
                    "excluded_or_unsupported": exclusions,
                    "profile": selected_profile.identity(),
                }
                write_json(directory / "context.json", config)
                pin, llama = load_model_pins().get(selected_profile.model_id), load_llama_cpp_pin()
                runs.create(
                    ReviewRun(
                        id=run_id,
                        snapshot_id=snapshot.id,
                        run_type=RunType.LIVE,
                        lifecycle=RunLifecycle.QUEUED,
                        created_at=datetime.now(UTC),
                        coverage=coverage,
                        model=ModelRef(
                            id=pin.id, file_sha256=pin.sha256, quantization=pin.quantization
                        ),
                        toolchain=Toolchain(
                            llama_cpp_release=llama.release,
                            llama_cpp_build=llama.build,
                            backend=selected_profile.backend,
                            opengrep_version=context.preparation.scan.observation.tool_version,
                            opengrep_rules_sha256=str(
                                context.preparation.scan.observation.inputs["rules_sha256"]
                            ),
                        ),
                    ),
                    questions,
                )
            else:
                run_id = args.run_id
                if re.fullmatch(r"review-[0-9a-f]{32}", run_id) is None:
                    raise ValueError("invalid review ID")
                directory = settings.data_dir / "reviews" / run_id
                config = json.loads((directory / "context.json").read_text(encoding="utf-8"))
                if config["implementation"] != implementation_identity():
                    raise ValueError("Investigator implementation changed; start a new review")
                run = runs.run(run_id)
                if run is None or run.snapshot_id != config["snapshot_id"]:
                    raise ValueError("run does not match its frozen context")
                if run.run_type is not RunType.LIVE:
                    raise ValueError(
                        "Saved/replayed runs cannot resume live inference; start a new review"
                    )
                if ready is not None and run.lifecycle not in {
                    RunLifecycle.PAUSED,
                    RunLifecycle.QUEUED,
                }:
                    raise ValueError("This review is no longer paused or queued")
                saved_profile = config.get("profile")
                if saved_profile is None:
                    raise ValueError("Review predates pinned profile identity; start a new review")
                requested = args.profile or saved_profile["id"]
                selected_profile = select(settings, requested)
                validate_resume(selected_profile, saved_profile, run)
                context = Review(settings, run.snapshot_id)
                if "policies_sha256" in config:
                    from backend.contracts.policies import FrozenPolicies

                    saved_policies = (directory / "policies.json").read_bytes()
                    if hashlib.sha256(saved_policies).hexdigest() != config["policies_sha256"]:
                        raise ValueError("Frozen policy requirements changed; start a new review")
                    context.policies = FrozenPolicies.model_validate_json(saved_policies)
                    context.validate_policies()
                # Legacy reviews retain their original empty requirement set.
                if "scheduling_sha256" in config:
                    from backend.scheduling import Preparation

                    saved = (directory / "scheduling.json").read_bytes()
                    if hashlib.sha256(saved).hexdigest() != config["scheduling_sha256"]:
                        raise ValueError(
                            "Saved scheduling observations changed; start a new review"
                        )
                    context.preparation = Preparation.model_validate_json(saved)
                    if context.preparation.supplementary and (
                        context.preparation.supplementary.run_id != run_id
                        or context.preparation.supplementary.snapshot_id != run.snapshot_id
                    ):
                        raise ValueError("Supplementary signals belong to another run/snapshot")
                    if (
                        context.preparation.peers.snapshot_id != run.snapshot_id
                        or context.preparation.scan.observation.run_id != run_id
                        or context.preparation.peer_observation.run_id != run_id
                    ):
                        raise ValueError("Scheduling observations belong to a different review")
                    limits = config.get("scheduling_limits")
                    if not isinstance(limits, list) or any(not isinstance(v, str) for v in limits):
                        raise ValueError("Invalid saved scheduling limitations")
                    context.scheduling_limits = limits
            print(
                f"Run: {run_id}\nReports: {directory}\n"
                f"Selected families: {', '.join(config.get('families', ['authorization']))}",
                flush=True,
            )
            if server is None:
                server = create(settings, run_id, selected_profile)
            if ready is not None:
                ready(run_id)
            model_pin = load_model_pins().get(selected_profile.model_id).model_dump(mode="json")
            launch = server.config.argv(0, "<per-launch key>")
            manifest.update(
                {
                    "run_id": run_id,
                    "snapshot_id": context.snapshot.id,
                    "model": model_pin,
                    "llama_cpp": load_llama_cpp_pin().model_dump(mode="json"),
                    "server_argv": launch,
                    "implementation": implementation_identity(),
                    "machine_start": machine_state(),
                    "scope": config,
                    "profile": selected_profile.identity(),
                }
            )

            def preflight() -> PreflightResult:
                result = server.preflight()
                manifest["preflights"].append(asdict(result))
                return result

            adapter = ModelAdapter(server, preflight=preflight)

            class Recorder:
                def ask(self, request: ModelRequest, spend: Spend) -> JsonAnswer:
                    row: dict[str, Any] = {
                        "request": request.body(),
                        "started": datetime.now(UTC).isoformat(),
                    }
                    manifest["requests"].append(row)
                    answer = adapter.ask(request, spend)
                    row["answer"] = asdict(answer)
                    print(f"  {request.name}: answered", flush=True)
                    return answer

            try:
                workflow = Workflow(
                    context,
                    runs,
                    run_id,
                    Recorder(),
                    Path(config["guard_cache"]),
                    json.dumps(selected_profile.identity(), sort_keys=True)
                    + json.dumps(model_pin, sort_keys=True)
                    + json.dumps(launch),
                    args.limit,
                )
                result = workflow.run()
                manifest["lifecycle"] = result.lifecycle.value
            except KeyboardInterrupt:
                interrupted = runs.run(run_id)
                if interrupted and interrupted.lifecycle is RunLifecycle.RUNNING:
                    runs.record(
                        interrupted.model_copy(update={"lifecycle": RunLifecycle.PAUSED}),
                        datetime.now(UTC),
                        clear_request=True,
                    )
                print("Interrupted. Saved checkpoints can be resumed.", flush=True)
            finally:
                adapter.close()
                bundle = export(context, runs, run_id, directory)
                manifest["coverage"] = bundle.run.coverage.model_dump(mode="json")
                manifest["findings"] = [
                    {"id": f.id, "conclusion": f.conclusion.value} for f in bundle.findings
                ]
                manifest["validated_guard_cache_hits"] = (
                    workflow._challenge.peers.classifier.cache_hits
                    if workflow is not None and workflow._challenge
                    else 0
                )
            print(summary(bundle), flush=True)
            print(
                f"Saved {directory / 'report.html'}\nView with: plumb report {run_id}", flush=True
            )
            if args.open_report:
                try:
                    show(settings, run_id, open_browser=True)
                except (OSError, ValueError):
                    print("Report opening refused; the saved report remains at the printed path.")
            unfinished = any(
                q.status not in (QuestionStatus.ANSWERED, QuestionStatus.EXCLUDED)
                for q in runs.questions(run_id)
            )
            return 0 if bundle.run.lifecycle is RunLifecycle.COMPLETED and not unfinished else 2
    except Exception as error:
        if failed is not None:
            failed(error)
        from backend.redaction import Redactor

        message = Redactor.configured().text(f"{type(error).__name__}: {error}")
        manifest["error"] = message
        print(f"Review stopped: {message}", flush=True)
        return 1
    finally:
        if server is not None:
            server.stop()
            manifest["memory_abort"] = server.memory_abort
        if context is not None:
            context.close()
        if directory is not None:
            manifest["finished"] = datetime.now(UTC).isoformat()
            manifest["machine_end"] = machine_state()
            from backend.redaction import Redactor

            write_json(
                directory / f"invocation-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}.json",
                Redactor.configured().strings(manifest),
            )


if __name__ == "__main__":
    raise SystemExit(main())

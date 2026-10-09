"""Protected readiness and explicit static folder inspection. No target execution."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from analysis.overview import overview
from analysis.paths import canonical_root, is_link
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.capabilities import table
from backend.case_reads import bounded
from backend.contracts.common import LinkStatus
from backend.contracts.runs import Condition, ConditionKind
from backend.contracts.setup_view import InspectionView, SetupReadiness
from backend.jobs import WorkerLock
from backend.redaction import Redactor
from backend.review import Review
from backend.settings import Settings
from backend.setup.__main__ import helper_status, preview
from backend.source_binding import bind


def readiness(settings: Settings) -> SetupReadiness:
    with WorkerLock(settings.cache_dir / "review.lock"):
        plan = preview(settings)
    report = plan["doctor"]
    profile = report["profiles"][0]
    model = next(m for m in report["model_candidates"] if m["id"] == profile["model_id"])
    conditions = []
    if not model["verified_installed"]:
        conditions.append(
            Condition(
                kind=ConditionKind.SETUP_REQUIRED,
                message="Plumb needs a verified local model to investigate. "
                f"{model['id']} is {model['size_bytes'] / 1_000_000_000:.1f} GB. "
                "No download has started.",
                action="Preview setup in the terminal before approving downloads.",
            )
        )
    if (
        not plan["typescript_helper"]["ready"]
        or not profile["runtime_verified"]
        or not profile["compatible_measured_host"]
        or not profile["pins_match"]
        or profile["runtime_compatible"] is not True
    ):
        conditions.append(
            Condition(
                kind=ConditionKind.SETUP_REQUIRED,
                message="Review prerequisites or the measured hardware profile are unavailable. "
                "Source inspection needs the trusted TypeScript helper; "
                "no driver or Windows feature is changed.",
                action="Run plumb setup to read the next steps.",
            )
        )
    if not profile["estimated_memory_fit"]:
        ram = report["inventory"]["memory"]["available_bytes"]
        vram = profile["dedicated_free_bytes"]
        conditions.append(
            Condition(
                kind=ConditionKind.MODEL_TOO_LARGE,
                message=f"{ram / 1_000_000_000:.2f} GB RAM free; this measured profile requires "
                f"{profile['host_required_bytes'] / 1_000_000_000:.2f} GB RAM and "
                f"{profile['device_required_bytes'] / 1_000_000_000:.2f} GB dedicated VRAM. "
                "Dedicated VRAM available: "
                + (f"{vram / 1_000_000_000:.2f} GB." if vram is not None else "unknown."),
                action="Close other apps if needed, then check readiness again. "
                "Source inspection uses no model.",
            )
        )
    if not profile["minimum_download_disk_fit"]:
        conditions.append(
            Condition(
                kind=ConditionKind.SETUP_REQUIRED,
                message="The data volume cannot establish sufficient space "
                "even for the missing downloads.",
                action="Choose a writable external data directory "
                "with sufficient space in plumb setup.",
            )
        )
    conditions.append(
        Condition(
            kind=ConditionKind.RUNNER_UNAVAILABLE,
            message="General runtime verification is unavailable. "
            "Source investigations retain their static evidence. "
            "The bundled hash-pinned Tandir runner is a separate capability.",
            action="Use source inspection and review; "
            "optional isolation setup is documented in README.",
        )
    )
    view = SetupReadiness(
        capabilities=table(),
        checked_at=datetime.now(UTC),
        ready=plan["ready"],
        inspect_ready=plan["typescript_helper"]["ready"],
        profile_id=profile["id"],
        model_id=profile["model_id"],
        model_size_bytes=model["size_bytes"],
        model_verified=profile["model_verified"],
        runtime_verified=profile["runtime_verified"],
        measured_host=profile["compatible_measured_host"] and profile["pins_match"],
        memory_fit=profile["estimated_memory_fit"],
        available_ram_bytes=report["inventory"]["memory"]["available_bytes"],
        required_ram_bytes=profile["host_required_bytes"],
        available_vram_bytes=profile["dedicated_free_bytes"],
        required_vram_bytes=profile["device_required_bytes"],
        missing_download_bytes=plan["missing_download_bytes"],
        requires_large_download_approval=plan["requires_large_download_approval"],
        conditions=conditions,
        limitations=[
            "A current readiness observation is not a reservation of memory. "
            "Every model launch repeats the unchanged memory gate.",
            report["memory_note"],
            report["disk_note"],
            profile["evaluated_capability"],
            "Only the existing measured profile can be selected; "
            "unmeasured models or hardware are not automatically approved.",
        ],
    )
    return bounded(
        SetupReadiness.model_validate(
            Redactor.configured(settings).strings(view.model_dump(mode="json"))
        )
    )


def authorized_root(folder: str, settings: Settings) -> Path:
    # Never let a folder field initiate UNC/network or device access, or scan a whole volume.
    if folder.startswith(("\\\\", "//")) or any(ord(c) < 32 for c in folder):
        raise ValueError("Use an absolute local project folder.")
    path = Path(folder)
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError("Use a project folder rather than a volume root.")
    if any(is_link(p.lstat()) for p in (path, *path.parents) if p != Path(p.anchor)):
        raise ValueError("Linked folder roots are unavailable.")
    root = canonical_root(path)
    data = settings.data_dir.resolve()
    if data.is_relative_to(root) or root.is_relative_to(data):
        raise ValueError("Project and Plumb storage must be separate.")
    return root


def inspect_folder(settings: Settings, folder: str) -> InspectionView:
    root = authorized_root(folder, settings)
    with WorkerLock(settings.cache_dir / "review.lock"):
        if not helper_status(settings)["ready"]:
            raise ValueError("Source inspection requires setup of the trusted helper.")
        snapshot = take_snapshot(root, SnapshotStore(settings.cache_dir / "snapshots"))
        review = Review(settings, snapshot.id)
        try:
            result = overview(snapshot, review.map, review.access, review.store)
            graph = result.graph
            reasons = Counter(f.reason.value for f in snapshot.excluded)
            conditions = []
            if reasons["unreadable"]:
                conditions.append(
                    Condition(
                        kind=ConditionKind.UNREADABLE_FILE,
                        message=f"{reasons['unreadable']} paths could not be read "
                        "and were excluded.",
                        action="Check file permissions and inspect again. "
                        "No conclusion is available for these paths.",
                    )
                )
            if not graph.entries:
                conditions.append(
                    Condition(
                        kind=ConditionKind.UNSUPPORTED_FRAMEWORK,
                        message="No supported entry points were discovered. "
                        "Included files may contain unsupported flows.",
                        action="Read scope before selecting a review. "
                        "This is not a clean bill of health.",
                    )
                )
            if snapshot.excluded or any(
                e.framework.value not in {"fastapi", "nextjs"} for e in graph.entries
            ):
                conditions.append(
                    Condition(
                        kind=ConditionKind.PARTIAL_COVERAGE,
                        message=f"{len(snapshot.files)} files included; "
                        f"{len(snapshot.excluded)} paths or directories excluded. "
                        "Discovered entry points do not cover every security issue.",
                        action="Read the excluded-path reasons and unsupported scope "
                        "before reviewing.",
                    )
                )
            view = InspectionView(
                capabilities=result.capabilities,
                inspection_id=bind(settings, root, snapshot.id),
                snapshot_id=snapshot.id,
                name=snapshot.root_name,
                captured_at=snapshot.created_at,
                languages=result.languages,
                frameworks=result.frameworks,
                resources=result.resources,
                included_files=len(snapshot.files),
                excluded_files=len(snapshot.excluded),
                exclusion_reasons=dict(reasons),
                entries=sorted(graph.entries, key=lambda e: (e.span.path, e.span.start_line, e.id))[
                    :12
                ],
                entries_total=len(graph.entries),
                unresolved_links=sum(link.status is LinkStatus.UNRESOLVED for link in graph.links),
                conditions=conditions,
                limitations=result.limitations,
            )
            clean = Redactor.configured(settings).strings(view.model_dump(mode="json"))
            if (
                clean["snapshot_id"] != view.snapshot_id
                or clean["entries"] != view.model_dump(mode="json")["entries"]
            ):
                raise ValueError(
                    "Redaction changed source identities; inspection cannot be displayed."
                )
            return bounded(InspectionView.model_validate(clean))
        finally:
            review.close()

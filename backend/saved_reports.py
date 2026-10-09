"""Validated saved-report navigation. No analyzer, model, server or worker starts here."""

import os
import re
import sys
import webbrowser
from collections import Counter
from pathlib import Path

from analysis.snapshot import SnapshotStore
from backend.contracts.investigation import Conclusion
from backend.contracts.runs import RunType
from backend.redaction import Redactor
from backend.reports import ReportBundle, render
from backend.settings import Settings

MAX_REPORT_BYTES = 16 * 1024**2


def load(
    settings: Settings,
    run_id: str,
    *,
    include_replay: bool = True,
    include_dispositions: bool = True,
) -> tuple[ReportBundle, Path]:
    if re.fullmatch(r"review-[0-9a-f]{32}", run_id) is None:
        raise ValueError("Invalid saved review ID")
    root = (settings.data_dir / "reviews").resolve(strict=True)
    directory = (root / run_id).resolve(strict=True)
    if directory.parent != root:
        raise ValueError("Review directory leaves the saved review root")
    paths = [directory / name for name in ("report.json", "report.html")]
    for path in paths:
        if path.resolve(strict=True).parent != directory:
            raise ValueError("Report file leaves the saved review directory")
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError("Saved report exceeds the navigation size limit")
    bundle = ReportBundle.model_validate_json(paths[0].read_bytes())
    if bundle.run.id != run_id:
        raise ValueError("Report belongs to a different review")
    store = SnapshotStore(settings.cache_dir / "snapshots")
    try:
        store.load(bundle.snapshot.id)
    except FileNotFoundError:
        store = SnapshotStore(settings.cache_dir)
    # Refuse modified HTML rather than asking the browser to trust arbitrary local markup.
    secrets = Redactor.configured(settings).secrets
    if paths[1].read_bytes() != render(bundle, store, "html", secrets=secrets).encode("utf-8"):
        raise ValueError("Saved HTML differs from validated evidence or current redaction")
    prepared = ReportBundle.model_validate_json(render(bundle, store, "json", secrets=secrets))
    effective, path = prepared, paths[1]
    if include_replay and (directory / "receipt-replay").exists():
        from verification.report_replay import load_attachment

        effective, path = load_attachment(directory, prepared, store, secrets)
    if include_dispositions:
        from backend.disposition_store import DispositionStore

        effective = DispositionStore(settings.cache_dir / "dispositions.sqlite").project(
            prepared, effective
        )
        effective = ReportBundle.model_validate_json(
            render(effective, store, "json", secrets=secrets)
        )
    return effective, path


def summary(bundle: ReportBundle) -> str:
    coverage = bundle.run.coverage
    counts = Counter(f.conclusion for f in bundle.findings)
    lines = [
        f"Run {bundle.run.id}: {bundle.run.lifecycle.value} ({bundle.run.run_type.value})",
        f"Source conclusions: {counts[Conclusion.SUPPORTED]} supported, "
        f"{counts[Conclusion.REJECTED]} rejected, {counts[Conclusion.INCONCLUSIVE]} inconclusive",
        f"Scope: {coverage.completed}/{coverage.total} checks processed; "
        f"{coverage.pending} pending, {coverage.excluded} excluded, "
        f"{coverage.unsupported} unsupported",
        "Source support and runtime reproduction are separate; see each finding's evidence.",
    ]
    if not bundle.findings:
        lines.append(
            "No finding records. No checks have completed yet."
            if not coverage.completed
            else "No finding records. This does not establish that the project is safe."
        )
    if coverage.pending and bundle.run.run_type is RunType.LIVE:
        lines.append(f"Resume eligible checkpoints with: plumb resume {bundle.run.id}")
    elif coverage.pending:
        lines.append(
            "Saved/replayed pending checks require a new live review; this artifact cannot resume."
        )
    lines.extend(f"Limit: {limit}" for limit in bundle.limitations)
    if bundle.disposition_history:
        lines.append("Current reviewer decisions (original HTML is immutable):")
        lines.extend(
            f"{f.display_id}: {f.disposition.value}; {f.disposition_reason}"
            for f in bundle.findings
            if any(d.finding_id == f.id for d in bundle.disposition_history)
        )
    return Redactor.configured().text("\n".join(lines))


def launch(path: Path) -> bool:
    """Dispatch a validated local file to the owner's default browser; headless can refuse."""
    if sys.platform == "win32":
        os.startfile(str(path), "open")  # noqa: S606 - validated local report, no command string
        return True  # Dispatch accepted, not a claim that a browser rendered the page.
    return webbrowser.open(path.as_uri(), new=2)


def show(settings: Settings, run_id: str, *, open_browser: bool = False) -> int:
    bundle, path = load(settings, run_id)
    print(summary(bundle), flush=True)
    print(Redactor.configured().text(f"Saved HTML: {path}"), flush=True)
    if open_browser:
        try:
            if launch(path):
                print("Browser opening requested. If no window appears, open the saved path.")
                return 0
        except (OSError, webbrowser.Error):
            pass
        print("Browser launch unavailable. The report is preserved; open the saved path yourself.")
        return 2
    print(f"Request browser opening with: plumb report {run_id} --open", flush=True)
    return 0

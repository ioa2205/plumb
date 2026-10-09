import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, Draft202012Validator
from pydantic import ValidationError

from agent.tests.test_validator import ORDERS_PY, T0, Lab
from analysis.snapshot import SnapshotStore, take_snapshot
from backend.contracts.investigation import Conclusion, ExhibitRole, RuntimeVerification, Severity
from backend.contracts.runs import Condition, Coverage, ReviewRun, RunLifecycle, RunStage
from backend.reports import BASE_LIMITATIONS, Format, ReportBundle, render
from backend.reports.__main__ import main

SCHEMAS = Path(__file__).resolve().parents[1] / "reports/schemas"
FORMATS = ("markdown", "html", "json", "sarif")


@dataclass
class Fixture:
    lab: Lab
    bundle: ReportBundle


@pytest.fixture
def sample(tmp_path: Path) -> Fixture:
    lab = Lab(tmp_path)
    supported = lab.finding(
        checks=[{"item": "Scoped query", "searched": "api/routes/orders.py:10-13", "found": False}],
        unknowns=["No isolated runner was available."],
    )
    rejected = lab.rejected().model_copy(
        update={
            "id": "finding:2",
            "display_id": "F-08",
            "title": "Invoice access is scoped to its owner",
            "lede": "The invoice route compares the order's customer with the caller.",
        }
    )
    guard = lab.owner_guard().model_copy(
        update={"subject": "user.id", "object": "order.customer_id"}
    )
    run = ReviewRun(
        id="run:1",
        snapshot_id=lab.snapshot.id,
        run_type="saved",
        lifecycle="completed",
        created_at=T0,
        started_at=T0,
        finished_at=T0,
        finding_ids=[supported.id, rejected.id],
        coverage=Coverage(total=2, completed=2),
    )
    return Fixture(
        lab,
        ReportBundle(
            run=run,
            snapshot=lab.snapshot,
            findings=[supported, rejected],
            guards=[guard],
            limitations=["Synthetic contract fixture; no model judgments were run."],
        ),
    )


def sarif_errors(text: str) -> list[str]:
    schema = json.loads((SCHEMAS / "sarif-schema-2.1.0.json").read_text())
    validator = Draft7Validator(schema, format_checker=Draft7Validator.FORMAT_CHECKER)
    return [error.message for error in validator.iter_errors(json.loads(text))]


@pytest.mark.parametrize("format", FORMATS)
def test_exports_share_configured_literal_redaction(
    sample: Fixture, monkeypatch: pytest.MonkeyPatch, format: Format
) -> None:
    literal = "configured fixture value"
    monkeypatch.setenv("PLUMB_REDACTION_SECRETS", json.dumps([literal]))
    bundle = sample.bundle.model_copy(update={"limitations": [literal]})
    output = render(bundle, sample.lab.store, format)
    assert literal not in output
    assert "REDACTED" in output


def test_schema_is_the_pinned_complete_oasis_schema() -> None:
    data = (SCHEMAS / "sarif-schema-2.1.0.json").read_bytes()
    assert (
        hashlib.sha256(data).hexdigest()
        == "2b19d2358baef0251d7d24e208d05ffabf1b2a3ab5e1b3a816066fc57fd4a7e8"
    )
    Draft7Validator.check_schema(json.loads(data))


@pytest.mark.parametrize("format", FORMATS)
def test_every_format_keeps_evidence_and_limitations(sample: Fixture, format: str) -> None:
    output = render(sample.bundle, sample.lab.store, format)  # ty: ignore[invalid-argument-type]
    for finding in sample.bundle.findings:
        assert finding.display_id in output
        assert finding.exhibits[0].span.content_sha256 in output
    assert sample.lab.snapshot.id in output
    assert "Synthetic contract fixture" in output
    assert "No isolated runner was available" in output
    assert "Static support does not establish runtime reproduction" in output
    assert "not_attempted" in output.replace("\\_", "_")
    if format in ("markdown", "html", "sarif"):
        assert "F-07/E01" in output and "F-08/E01" in output
        assert "Scoped query" in output and "not found" in output.lower()
    if format == "sarif":
        assert sarif_errors(output) == []
        results = json.loads(output)["runs"][0]["results"]
        assert [(r["kind"], r["level"]) for r in results] == [
            ("fail", "error"),
            ("notApplicable", "none"),
        ]
        assert [r["relatedLocations"][0]["properties"]["evidenceId"] for r in results] == [
            "F-07/E01",
            "F-08/E01",
        ]
        assert results[1]["properties"]["finding"]["checks"][0]["exhibit_tag"] == "E01"
    if format == "json":
        saved = ReportBundle.model_validate_json(output)
        assert saved.findings == sample.bundle.findings
        assert all(limitation in saved.limitations for limitation in BASE_LIMITATIONS)


@pytest.mark.parametrize("format", FORMATS)
def test_source_impact_rationale_and_links_survive_export(sample: Fixture, format: Format) -> None:
    from agent.severity import _apply

    case = sample.bundle.findings[0].model_copy(update={"severity": Severity.UNKNOWN})
    rated = _apply(
        case,
        Severity.MEDIUM,
        "Scoped record read through a declared HTTP entry.",
        [case.exhibits[0].span],
        sample.lab.validator,
    )
    assert rated.severity is Severity.MEDIUM
    bundle = sample.bundle.model_copy(update={"findings": [rated, *sample.bundle.findings[1:]]})
    output = render(bundle, sample.lab.store, format)
    if format == "markdown":
        output = re.sub(r"\\(.)", r"\1", output)
    assert rated.severity_rationale in output
    if format == "json":
        assert ReportBundle.model_validate_json(output).findings[0] == rated
    elif format == "sarif":
        assert not sarif_errors(output)
        first = json.loads(output)["runs"][0]["results"][0]
        assert first["level"] == "warning"
        assert first["properties"]["finding"] == rated.model_dump(mode="json")
    if format != "json":
        assert f"{rated.display_id}/{rated.exhibits[0].tag}" in output


@pytest.mark.parametrize("conclusion", list(Conclusion))
@pytest.mark.parametrize("severity", list(Severity))
def test_sarif_status_and_severity_are_independent(
    sample: Fixture, conclusion: Conclusion, severity: Severity
) -> None:
    base = sample.bundle.findings[1 if conclusion is Conclusion.REJECTED else 0]
    finding = base.model_copy(update={"conclusion": conclusion, "severity": severity})
    run = sample.bundle.run.model_copy(update={"finding_ids": [finding.id]})
    bundle = sample.bundle.model_copy(update={"run": run, "findings": [finding]})
    output = render(bundle, sample.lab.store, "sarif")
    assert sarif_errors(output) == []
    result = json.loads(output)["runs"][0]["results"][0]
    kinds = {
        "supported": "fail",
        "rejected": "notApplicable",
        "candidate": "review",
        "inconclusive": "open",
    }
    assert result["kind"] == kinds[conclusion.value]
    assert result["properties"]["finding"]["severity"] == severity.value
    if conclusion is not Conclusion.SUPPORTED:
        assert result["level"] == "none"


@pytest.mark.parametrize("format", FORMATS)
def test_partial_and_empty_runs_are_honest(sample: Fixture, format: str) -> None:
    run = sample.bundle.run.model_copy(
        update={
            "lifecycle": RunLifecycle.PAUSED,
            "stage": RunStage.INVESTIGATING,
            "finished_at": None,
            "finding_ids": [],
            "coverage": Coverage(total=6, completed=1, pending=2, excluded=1, unsupported=2),
            "conditions": [Condition(kind="model_too_large", message="Memory preflight refused.")],
        }
    )
    bundle = sample.bundle.model_copy(update={"run": run, "findings": []})
    output = render(bundle, sample.lab.store, format)  # ty: ignore[invalid-argument-type]
    assert "paused" in output and "2 questions remain pending" in output
    assert "Memory preflight refused" in output
    assert "excluded" in output and "unsupported" in output
    if format in ("html", "markdown"):
        assert "No findings recorded" in output
    if format == "sarif":
        assert sarif_errors(output) == []
        run_data = json.loads(output)["runs"][0]
        assert run_data["invocations"][0]["executionSuccessful"] is False
        assert run_data["results"] == []
        assert run_data["properties"]["plumbReport"]["run"]["coverage"]["total"] == 6


@pytest.mark.parametrize("format", FORMATS)
@pytest.mark.parametrize("bad", ["hash", "comment", "reproduced", "guard", "no evidence"])
def test_no_export_format_can_bypass_the_validator(sample: Fixture, format: str, bad: str) -> None:
    finding = sample.bundle.findings[0]
    guards = sample.bundle.guards
    if bad == "hash":
        exhibit = finding.exhibits[0]
        span = exhibit.span.model_copy(update={"content_sha256": "0" * 64})
        finding = finding.model_copy(
            update={"exhibits": [exhibit.model_copy(update={"span": span})]}
        )
    elif bad == "comment":
        exhibit = finding.exhibits[0].model_copy(update={"span": sample.lab.span(ORDERS_PY, 8, 9)})
        finding = finding.model_copy(update={"exhibits": [exhibit]})
    elif bad == "reproduced":
        finding = finding.model_copy(
            update={
                "runtime_verification": RuntimeVerification.REPRODUCED,
                "probe_run_ids": ["missing"],
            }
        )
    elif bad == "guard":
        finding = sample.bundle.findings[1]
        guards = []
    else:
        finding = finding.model_copy(update={"exhibits": []})
    run = sample.bundle.run.model_copy(update={"finding_ids": [finding.id]})
    bundle = sample.bundle.model_copy(update={"findings": [finding], "guards": guards, "run": run})
    with pytest.raises(ValueError):
        render(bundle, sample.lab.store, format)  # ty: ignore[invalid-argument-type]


def test_forged_confirmed_guard_is_checked_again(sample: Fixture) -> None:
    guard = sample.bundle.guards[0].model_copy(update={"object": "order.id"})
    with pytest.raises(ValueError, match="holds no test"):
        render(sample.bundle.model_copy(update={"guards": [guard]}), sample.lab.store, "json")


def test_reproduced_requires_the_recorded_attack_and_control(sample: Fixture) -> None:
    probe = sample.lab.run()
    finding = sample.bundle.findings[0].model_copy(
        update={"runtime_verification": RuntimeVerification.REPRODUCED, "probe_run_ids": [probe.id]}
    )
    bundle = sample.bundle.model_copy(
        update={"findings": [finding, sample.bundle.findings[1]], "probe_runs": [probe]}
    )
    output = render(bundle, sample.lab.store, "sarif")
    assert sarif_errors(output) == []
    assert (
        json.loads(output)["runs"][0]["properties"]["plumbReport"]["probe_runs"][0]["outcome"]
        == "reproduced"
    )
    broken = probe.model_copy(update={"steps": [probe.steps[0]]})
    with pytest.raises(ValidationError):
        render(bundle.model_copy(update={"probe_runs": [broken]}), sample.lab.store, "sarif")


@pytest.mark.parametrize(
    "bad",
    [
        "wrong run",
        "wrong snapshot",
        "duplicate ID",
        "duplicate display",
        "missing finding",
        "blank limitation",
    ],
)
def test_export_refuses_inconsistent_records(sample: Fixture, bad: str) -> None:
    bundle = sample.bundle
    findings = bundle.findings.copy()
    if bad == "wrong run":
        findings[0] = findings[0].model_copy(update={"run_id": "foreign"})
    elif bad == "wrong snapshot":
        bundle = bundle.model_copy(
            update={"snapshot": bundle.snapshot.model_copy(update={"root_name": "changed"})}
        )
    elif bad == "duplicate ID":
        findings[1] = findings[1].model_copy(update={"id": findings[0].id})
    elif bad == "duplicate display":
        findings[1] = findings[1].model_copy(update={"display_id": findings[0].display_id})
    elif bad == "missing finding":
        findings.pop()
    else:
        bundle = bundle.model_copy(update={"limitations": [" "]})
    with pytest.raises(ValueError):
        render(bundle.model_copy(update={"findings": findings}), sample.lab.store, "json")


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)


def test_html_and_markdown_render_hostile_text_as_text(sample: Fixture) -> None:
    hostile = (
        "<script>alert(1)</script> [click](javascript:evil) <img src=x onerror=evil>\n# injected"
    )
    finding = sample.bundle.findings[0].model_copy(update={"title": hostile, "lede": hostile})
    bundle = sample.bundle.model_copy(update={"findings": [finding, sample.bundle.findings[1]]})
    output = render(bundle, sample.lab.store, "html")
    parsed = Tags()
    parsed.feed(output)
    assert "script" not in parsed.tags and "img" not in parsed.tags
    assert all(
        value and value.startswith("#") for name, value in parsed.attributes if name == "href"
    )
    assert not any(name.startswith("on") for name, _ in parsed.attributes)
    assert "Content-Security-Policy" in output
    assert "&lt;script&gt;" in output
    markdown = render(bundle, sample.lab.store, "markdown")
    assert "<script>" not in markdown and "\n# injected" not in markdown
    assert "[click](javascript:evil)" not in markdown


@pytest.mark.parametrize("format", FORMATS)
def test_redaction_is_shared_and_keeps_evidence_identity(sample: Fixture, format: str) -> None:
    credential = "ghp_" + "x" * 36
    literal = "session-fixture-value"
    finding = sample.bundle.findings[0].model_copy(
        update={"lede": f"api_key={credential}; {literal}"}
    )
    bundle = sample.bundle.model_copy(
        update={
            "findings": [finding, sample.bundle.findings[1]],
            "limitations": [f"Token: {credential}"],
        }
    )
    output = render(bundle, sample.lab.store, format, secrets=[literal])  # ty: ignore[invalid-argument-type]
    assert credential not in output and literal not in output
    assert "REDACTED" in output
    assert finding.id in output
    assert finding.exhibits[0].span.content_sha256 in output
    assert sample.bundle.findings[0].lede != finding.lede  # input objects were not mutated
    if format == "sarif":
        assert sarif_errors(output) == []


def test_redaction_of_an_evidence_id_is_refused(sample: Fixture) -> None:
    with pytest.raises(ValueError, match="citation identity"):
        render(sample.bundle, sample.lab.store, "json", secrets=["finding:1"])


def test_html_allows_only_the_exact_trusted_style_and_local_anchors(sample: Fixture) -> None:
    output = render(sample.bundle, sample.lab.store, "html")
    css = re.findall(r"<style>(.*?)</style>", output, flags=re.DOTALL)
    assert len(css) == 1
    digest = base64.b64encode(hashlib.sha256(css[0].encode()).digest()).decode()
    parsed = Tags()
    parsed.feed(output)
    policy = next(
        value
        for name, value in parsed.attributes
        if name == "content" and "style-src" in (value or "")
    )
    assert policy and f"style-src 'sha256-{digest}'" in policy
    assert "default-src 'none'" in policy and "unsafe-inline" not in policy
    assert not any(
        name in {"style", "src"} or name.startswith("on") for name, _ in parsed.attributes
    )
    assert not any(tag in {"script", "iframe", "object", "form"} for tag in parsed.tags)
    ids = [value for name, value in parsed.attributes if name == "id"]
    assert len(ids) == len(set(ids))
    for name, value in parsed.attributes:
        if name == "href":
            assert value and value.startswith("#") and value[1:] in ids
    assert "url(" not in css[0] and "@import" not in css[0]


@pytest.mark.parametrize(
    ("attack", "control", "outcome", "runtime", "summary"),
    [
        ((200, True), (200, True), "reproduced", RuntimeVerification.REPRODUCED, "bob received"),
        (
            (404, False),
            (200, True),
            "not_reproduced",
            RuntimeVerification.NOT_REPRODUCED,
            "bob was denied",
        ),
        (
            (200, True),
            (404, False),
            "inconclusive",
            RuntimeVerification.INCONCLUSIVE,
            "Recorded check: inconclusive",
        ),
        (
            (500, False),
            (200, True),
            "inconclusive",
            RuntimeVerification.INCONCLUSIVE,
            "Recorded check: inconclusive",
        ),
    ],
)
def test_html_proof_preserves_the_actual_control_oracle(
    sample: Fixture,
    attack: tuple[int, bool],
    control: tuple[int, bool],
    outcome: str,
    runtime: RuntimeVerification,
    summary: str,
) -> None:
    probe = sample.lab.run(attack=attack, control=control, outcome=outcome)
    finding = sample.bundle.findings[0].model_copy(
        update={"runtime_verification": runtime, "probe_run_ids": [probe.id]}
    )
    bundle = sample.bundle.model_copy(
        update={"findings": [finding, sample.bundle.findings[1]], "probe_runs": [probe]}
    )
    output = render(bundle, sample.lab.store, "html")
    assert summary in output
    assert "Source conclusion" in output and "Supported" in output
    assert "Runtime verification" in output
    assert "Cross-user check" in output and "Owner control" in output
    assert "Expected if safe: denied" in output and "Expected if safe: allowed" in output
    assert f"HTTP {attack[0]}" in output and f"HTTP {control[0]}" in output
    assert probe.id in output and probe.runner_manifest_sha256 in output
    if outcome == "inconclusive":
        assert "bob received" not in output and "owner control succeeded" not in output


def test_html_scope_counts_are_not_vulnerability_coverage(sample: Fixture) -> None:
    run = sample.bundle.run.model_copy(
        update={"coverage": Coverage(total=74, completed=2, excluded=72)}
    )
    output = render(sample.bundle.model_copy(update={"run": run}), sample.lab.store, "html")
    assert "2 / 74 completed" in output
    assert "2 completed, 0 pending, 72 excluded, 0 unsupported, 74 total" in output
    assert "do not measure the percentage of vulnerabilities found" in output
    assert "#coverage-excluded { flex-grow: 72; flex-basis: 0; }" in output
    assert "1 supported" in output and "1 rejected" in output
    assert "No runtime check was attempted" in output


def test_html_palette_text_has_aa_contrast_in_both_themes(sample: Fixture) -> None:
    output = render(sample.bundle, sample.lab.store, "html")
    blocks = re.findall(r"(?:^|\n):root[^{}]*\{([^}]+)\}", output)
    # Includes the base palette and explicit Night override, not the nested media rule.
    assert len(blocks) >= 2

    def luminance(color: str) -> float:
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    for block in blocks[:2]:
        tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", block))
        for foreground, background in (
            ("ink", "sheet"),
            ("graphite", "sheet"),
            ("pencil", "well"),
            ("pencil", "carmine-wash"),
            ("carmine", "carmine-wash"),
            ("blue", "sheet"),
            ("ochre", "ochre-wash"),
        ):
            light, dark = sorted((luminance(tokens[foreground]), luminance(tokens[background])))
            assert (dark + 0.05) / (light + 0.05) >= 4.5, (foreground, background)


def test_export_is_deterministic_and_reexport_does_not_duplicate_limitations(
    sample: Fixture,
) -> None:
    first = render(sample.bundle, sample.lab.store, "json")
    second = render(ReportBundle.model_validate_json(first), sample.lab.store, "json")
    assert first == second
    assert render(sample.bundle, sample.lab.store, "sarif") == render(
        sample.bundle, sample.lab.store, "sarif"
    )


@pytest.mark.parametrize("format", FORMATS)
def test_recapture_preserves_existing_report_exports(sample: Fixture, format: Format) -> None:
    before = render(sample.bundle, sample.lab.store, format)
    recaptured = take_snapshot(
        sample.lab.project,
        sample.lab.store,
        now=sample.bundle.snapshot.created_at + timedelta(days=1),
    )
    assert recaptured == sample.bundle.snapshot
    assert render(sample.bundle, sample.lab.store, format) == before


def test_report_bundle_schema_is_current_and_validates(sample: Fixture) -> None:
    stored = json.loads((SCHEMAS / "report-bundle.schema.json").read_text())
    expected = ReportBundle.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert stored == expected
    Draft202012Validator(stored).validate(sample.bundle.model_dump(mode="json"))


@pytest.mark.parametrize("layout", ["legacy", "review"])
def test_cli_exports_and_never_overwrites_a_file(
    sample: Fixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    layout: str,
) -> None:
    # Settings.cache_dir must point to this fixture's store, not the real data directory.
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path))
    destination = tmp_path / "cache"
    if layout == "review":
        destination = destination / "snapshots"
        destination.parent.mkdir()
    sample.lab.store.directory.rename(destination)
    input_path = tmp_path / "bundle.json"
    input_path.write_text(sample.bundle.model_dump_json(), encoding="utf-8")
    output_path = tmp_path / "report.sarif"
    assert main([str(input_path), "--format", "sarif", "--output", str(output_path)]) == 0
    before = output_path.read_text()
    assert sarif_errors(before) == []
    assert main([str(input_path), "--format", "json", "--output", str(output_path)]) == 1
    assert output_path.read_text() == before
    assert "FileExistsError" in capsys.readouterr().err


def test_cli_refusal_does_not_echo_sensitive_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.json"
    credential = "ghp_" + "z" * 36
    path.write_text(json.dumps({"run": credential}), encoding="utf-8")
    assert main([str(path)]) == 1
    captured = capsys.readouterr()
    assert credential not in captured.err + captured.out


def test_sarif_paths_are_encoded_relative_uris(sample: Fixture) -> None:
    output = json.loads(render(sample.bundle, sample.lab.store, "sarif"))
    for location in output["runs"][0]["results"][0]["relatedLocations"]:
        assert location["physicalLocation"]["artifactLocation"]["uri"] == ORDERS_PY
    # The main location cannot be a developer note even when it is listed first.
    finding = sample.bundle.findings[0]
    note = finding.exhibits[0].model_copy(update={"tag": "E02", "role": ExhibitRole.DEVELOPER_NOTE})
    finding = finding.model_copy(update={"exhibits": [note, *finding.exhibits]})
    bundle = sample.bundle.model_copy(update={"findings": [finding, sample.bundle.findings[1]]})
    result = json.loads(render(bundle, sample.lab.store, "sarif"))["runs"][0]["results"][0]
    assert result["locations"][0]["properties"]["evidenceId"] == "F-07/E01"


def test_sarif_encodes_spaces_percent_and_unicode_in_snapshot_paths(
    sample: Fixture, tmp_path: Path
) -> None:
    project = tmp_path / "unicode-project"
    project.mkdir()
    name = "buyurtma % caf\u00e9.py"
    (project / name).write_bytes((sample.lab.project / ORDERS_PY).read_bytes())
    store = SnapshotStore(tmp_path / "unicode-store")
    snapshot = take_snapshot(project, store)
    base = sample.bundle.findings[0]
    span = base.exhibits[0].span.model_copy(update={"snapshot_id": snapshot.id, "path": name})
    finding = base.model_copy(
        update={
            "snapshot_id": snapshot.id,
            "exhibits": [base.exhibits[0].model_copy(update={"span": span})],
        }
    )
    run = sample.bundle.run.model_copy(
        update={"snapshot_id": snapshot.id, "finding_ids": [finding.id]}
    )
    bundle = ReportBundle(run=run, snapshot=snapshot, findings=[finding])
    output = render(bundle, store, "sarif")
    assert sarif_errors(output) == []
    run_data = json.loads(output)["runs"][0]
    expected = "buyurtma%20%25%20caf%C3%A9.py"
    assert run_data["artifacts"][0]["location"]["uri"] == expected
    assert (
        run_data["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == expected
    )


def test_suggested_change_is_readable_and_cannot_escape_markdown_fence(sample: Fixture) -> None:
    change = sample.lab.change(status="proposed", replay_probe_run_ids=[])
    change = change.model_copy(update={"diff": change.diff + "-old\n+```\n+# injected\n"})
    finding = sample.bundle.findings[0].model_copy(update={"suggested_change_id": change.id})
    bundle = sample.bundle.model_copy(
        update={"findings": [finding, sample.bundle.findings[1]], "suggested_changes": [change]}
    )
    markdown = render(bundle, sample.lab.store, "markdown")
    assert "````diff\n" + change.diff.rstrip() + "\n````" in markdown
    assert "replayed_fixed" not in markdown
    for format in ("html", "json", "sarif"):
        output = render(bundle, sample.lab.store, format)
        assert change.id in output
    assert sarif_errors(render(bundle, sample.lab.store, "sarif")) == []


def test_missing_snapshot_blob_refuses_export(sample: Fixture) -> None:
    blob = sample.lab.store.blobs
    # Corrupt the test-owned blob, not the target project or shared data directory.
    file = next(item for item in sample.lab.snapshot.files if item.path == ORDERS_PY)
    path = blob.directory / file.sha256[:2] / file.sha256
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="corrupted"):
        render(sample.bundle, sample.lab.store, "json")


@pytest.mark.parametrize("record", ["foreign probe", "uncited probe", "uncited change"])
def test_unassociated_runtime_records_are_refused(sample: Fixture, record: str) -> None:
    if record == "uncited change":
        change = sample.lab.change(status="proposed", replay_probe_run_ids=[])
        bundle = sample.bundle.model_copy(update={"suggested_changes": [change]})
    else:
        probe = sample.lab.run(finding_id="foreign" if record == "foreign probe" else "finding:1")
        bundle = sample.bundle.model_copy(update={"probe_runs": [probe]})
    with pytest.raises(ValueError):
        render(bundle, sample.lab.store, "json")

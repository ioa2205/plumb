"""Private external SQLite storage; transactions merge concurrent append-only activity."""

import json
import sqlite3
import stat
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from backend.contracts.assessment import (
    AccessExpectation,
    AssessmentAnswer,
    AssessmentList,
    AssessmentScope,
    AssessmentView,
    AttachmentReview,
    ComparisonRequest,
    EvidenceArtifact,
    LabCollectionBinding,
    ObservationComparison,
    ReportPreview,
    TaskResolveRequest,
)
from backend.contracts.assessment_engine import (
    ControlledHTTPResult,
    ObservationAnalysis,
)
from backend.redaction import Redactor
from backend.settings import Settings

from .evidence import (
    SensitiveDiscovery,
    artifact_digest,
    check_scope,
    digest,
    parse_import,
    resolve_citation,
    sanitize_http_record,
    sanitize_observation_body,
    validate_observation_metadata,
)
from .planning import answer_task, compare_observations, interpret_prompt
from .reports import report_preview

MAX_VIEW_BYTES = 16 * 1024 * 1024
REPOSITORY = Path(__file__).resolve().parents[2]


def _link(path: Path) -> bool:
    return path.is_symlink() or bool(
        path.exists()
        and getattr(path.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


class AssessmentStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.redactor = Redactor.configured(self.settings)
        base = self.settings.data_dir.resolve()
        if base == REPOSITORY or REPOSITORY in base.parents:
            raise ValueError("private assessment data must live outside the repository")
        self.directory = base / "assessments"
        self.path = self.directory / "assessments.sqlite"

    def _safe_path(self, path: Path) -> Path:
        if path != self.directory and self.directory not in path.parents:
            raise ValueError("private assessment path escaped storage")
        for current in (path, *path.parents):
            if _link(current):
                raise ValueError("private assessment storage refuses links and reparse points")
        return path

    def _connect(self) -> sqlite3.Connection:
        self._safe_path(self.path)
        self.directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS assessments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        return connection

    def _validate(self, view: AssessmentView) -> AssessmentView:
        result = AssessmentView.model_validate(view.model_dump())
        redaction_input = result.model_dump(mode="json")
        for artifact in redaction_input["artifacts"]:
            if artifact["kind"] == "request_response":
                # Percent-encoded replacement text in credential queries is not
                # idempotent under generic assignment redaction. Exact scoped URL
                # sanitization below checks this field before storage/context/export.
                artifact["fields"].pop("request.url", None)
        if self.redactor.strings(redaction_input) != redaction_input:
            raise ValueError("assessment storage refuses unsanitized secrets")
        if (
            result.spent_requests > result.scope.budget.max_requests
            or result.spent_seconds > result.scope.budget.max_seconds
        ):
            raise ValueError("saved assessment exceeds its lifetime budget")
        ids = [artifact.artifact_id for artifact in result.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("assessment artifact IDs must be unique")
        accounts = {item.account_id for item in result.scope.accounts}
        objects = {item.object_id for item in result.scope.synthetic_objects}
        for artifact in result.artifacts:
            if (
                artifact.assessment_id != result.scope.assessment_id
                or artifact.sha256 != artifact_digest(artifact)
            ):
                raise ValueError("artifact identity/hash does not match its assessment")
            if artifact.context and (
                artifact.context.account_id not in accounts
                or artifact.context.object_id not in objects
            ):
                raise ValueError("artifact context is outside the designated test scope")
            if artifact.kind == "request_response":
                check = result.scope
                binding = artifact.trusted_lab_collection
                if binding:
                    from verification import lab

                    if (
                        result.scope.application_id != "owned-tandir"
                        or binding.scope_origin != result.scope.origin
                        or binding.manifest_sha256 != digest(lab.PIN.read_bytes())
                        or urlsplit(binding.runner_origin).hostname != "127.0.0.1"
                    ):
                        raise ValueError("trusted bundled-lab provenance does not resolve")
                    check = AssessmentScope.model_validate(
                        {**check.model_dump(), "origin": binding.runner_origin}
                    )
                # Saved evidence remains readable after expiry; all new actions check active scope.
                check_scope(
                    check, url=artifact.fields["request.url"], now=check.authority.granted_at
                )
                required = {
                    "request.method",
                    "request.url",
                    "request.body",
                    "response.status",
                    "response.body",
                }
                if not required <= artifact.fields.keys() or any(
                    field not in required
                    and not field.startswith("request.headers.")
                    and not field.startswith("response.headers.")
                    for field in artifact.fields
                ):
                    raise ValueError("saved observation field layout is unsupported")
                validate_observation_metadata(check, artifact.fields, self.redactor)
                markers = tuple(
                    item.synthetic_marker
                    for item in result.scope.synthetic_objects
                    if item.synthetic_marker
                )
                for field in ("request.body", "response.body"):
                    if (
                        sanitize_observation_body(artifact.fields[field], self.redactor, markers)
                        != artifact.fields[field]
                    ):
                        raise ValueError("saved observation body is not sanitized inert data")
            if artifact.attachment_path is not None:
                expected = (
                    self.directory
                    / result.scope.assessment_id
                    / "attachments"
                    / (artifact.fields["screenshot.sha256"] + ".png")
                )
                if (
                    Path(artifact.attachment_path) != expected
                    or digest(self._safe_path(expected).read_bytes())
                    != artifact.fields["screenshot.sha256"]
                ):
                    raise ValueError("reviewed screenshot attachment/hash does not resolve")
        for expectation in result.expectations:
            if (
                expectation.object_id not in objects
                or not set(expectation.allowed_account_ids) <= accounts
            ):
                raise ValueError("expectation references undesignated accounts or objects")
            check_scope(
                result.scope,
                url=result.scope.origin + expectation.path,
                now=result.scope.authority.granted_at,
            )
        for comparison in result.comparisons:
            replay_view = result.model_copy(update={"stopped": False})
            rebuilt = compare_observations(
                replay_view, comparison.request, now=result.scope.authority.granted_at
            )
            if rebuilt != comparison:
                raise ValueError("saved comparison does not match its underlying evidence")
            for citation in comparison.citations:
                resolve_citation(result, citation)
        for answer in result.answers:
            if answer.task.target_id != result.scope.assessment_id:
                raise ValueError("saved task belongs to a different assessment")
            for citation in answer.citations:
                resolve_citation(result, citation)
        for raw_analysis in result.analyses:
            if raw_analysis.get("generated_by") == "local_model":
                self._validate_analysis(result, ObservationAnalysis.model_validate(raw_analysis))
            elif raw_analysis.get("execution_status") == "collected_owned_lab":
                recorded = ControlledHTTPResult.model_validate(raw_analysis)
                if recorded.runner_origin is None:
                    raise ValueError("recorded runner trace lacks its runtime origin")
                if any(
                    artifact.trusted_lab_collection is None
                    or artifact.trusted_lab_collection.preview_sha256 != recorded.preview_sha256
                    for artifact in result.artifacts
                    if artifact.artifact_id in {row.get("artifact_id") for row in recorded.records}
                ):
                    raise ValueError("recorded runner trace does not bind its imported evidence")
            else:
                raise ValueError("saved assessment analysis has no supported typed provenance")
        if len(result.model_dump_json().encode()) > MAX_VIEW_BYTES:
            raise ValueError("private assessment exceeds the storage budget")
        return result

    def _validate_analysis(self, view: AssessmentView, analysis: ObservationAnalysis) -> None:
        from agent.web_assessment import (
            SEEDS,
            analysis_packet_hash,
            parse_recorded_judgment,
            validate_judgment,
        )

        comparison = next(
            (item for item in view.comparisons if item.comparison_id == analysis.comparison_id),
            None,
        )
        if comparison is None:
            raise ValueError("recorded analysis references an unknown comparison")
        if analysis.packet_sha256 != analysis_packet_hash(view, comparison):
            raise ValueError("recorded analysis packet hash does not match its exact evidence")
        if (
            analysis.requests_used < 0
            or analysis.requests_used > view.scope.budget.max_requests
            or analysis.seconds < 0
            or len(analysis.judgments) > 3
            or [sample.seed for sample in analysis.judgments]
            != list(SEEDS[: len(analysis.judgments)])
        ):
            raise ValueError("recorded analysis exceeds its declared judgments or budgets")
        valid = []
        for sample in analysis.judgments:
            if sample.answer is None or sample.error or sample.violations:
                continue
            if validate_judgment(view, comparison, sample.answer):
                raise ValueError("recorded local judgment no longer validates")
            if (
                sample.raw_answer is None
                or parse_recorded_judgment(view, comparison, sample.raw_answer) != sample.answer
            ):
                raise ValueError("recorded judgment does not match its saved raw answer")
            valid.append(sample.answer)
        verdicts = {answer.verdict for answer in valid}
        decisive = len(valid) == 3 and len(verdicts) == 1 and analysis.stop_reason is None
        if decisive and analysis.seconds > view.scope.budget.max_seconds:
            raise ValueError("decisive analysis exceeded its declared time budget")
        expected = next(iter(verdicts)) if decisive else "inconclusive"
        if analysis.conclusion != expected:
            raise ValueError("recorded analysis conclusion violates the three-judgment rule")
        expected_citations = {
            (claim.citation.artifact_id, claim.citation.field, claim.citation.sha256)
            for answer in valid
            for claim in answer.claims
        }
        actual_citations = {
            (citation.artifact_id, citation.field, citation.sha256)
            for citation in analysis.citations
        }
        if actual_citations != expected_citations:
            raise ValueError("recorded analysis citations differ from validated judgment claims")
        for citation in analysis.citations:
            resolve_citation(view, citation)

    def _read(self, connection: sqlite3.Connection, identity: str) -> AssessmentView:
        row = connection.execute(
            (
                "SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload "
                "ELSE NULL END FROM assessments WHERE id=?"
            ),
            (MAX_VIEW_BYTES, identity),
        ).fetchone()
        if row is None:
            raise ValueError("assessment does not exist")
        if row[0] is None:
            raise ValueError("saved assessment exceeds the read budget")
        view = self._validate(AssessmentView.model_validate_json(row[0]))
        if view.scope.assessment_id != identity:
            raise ValueError("saved assessment identity does not match its key")
        return view

    def _mutate(
        self, identity: str, change: Callable[[AssessmentView], AssessmentView]
    ) -> AssessmentView:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            view = self._read(connection, identity)
            updated = self._validate(change(view))
            connection.execute(
                "UPDATE assessments SET payload=? WHERE id=?", (updated.model_dump_json(), identity)
            )
            return updated

    def create(
        self, scope: AssessmentScope, *, expectations: tuple[AccessExpectation, ...] = ()
    ) -> AssessmentView:
        scope = AssessmentScope.model_validate(scope.model_dump())
        check_scope(scope)
        view = self._validate(AssessmentView(scope=scope, expectations=list(expectations)))
        with closing(self._connect()) as connection, connection:
            try:
                connection.execute(
                    "INSERT INTO assessments VALUES (?, ?)",
                    (scope.assessment_id, view.model_dump_json()),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("assessment ID already exists") from error
        return view

    def load(self, assessment_id: str) -> AssessmentView:
        if not self.path.exists():
            raise ValueError("assessment does not exist")
        with closing(self._connect()) as connection:
            return self._read(connection, assessment_id)

    def list_scopes(self) -> AssessmentList:
        if not self.path.exists():
            return AssessmentList(assessments=[])
        with closing(self._connect()) as connection:
            identities = [
                row[0]
                for row in connection.execute("SELECT id FROM assessments ORDER BY id LIMIT 101")
            ]
            if len(identities) > 100:
                raise ValueError("assessment listing exceeds its bounded page")
            return AssessmentList(
                assessments=[self._read(connection, identity).scope for identity in identities]
            )

    def save(self, view: AssessmentView) -> None:
        """Append-only merge prevents a slow worker from overwriting newer imports/stops."""
        incoming = self._validate(view)

        def merge(current: AssessmentView) -> AssessmentView:
            if incoming.scope != current.scope:
                raise ValueError(
                    "saved scope is immutable; prompts and workers cannot expand authority"
                )
            updates: dict[str, object] = {}
            for name, key in (
                ("artifacts", "artifact_id"),
                ("expectations", "expectation_id"),
                ("comparisons", "comparison_id"),
                ("answers", "answer_id"),
            ):
                indexed = {getattr(item, key): item for item in getattr(current, name)}
                for item in getattr(incoming, name):
                    identity = getattr(item, key)
                    if identity in indexed and indexed[identity] != item:
                        raise ValueError("saved evidence/activity is immutable")
                    indexed[identity] = item
                updates[name] = list(indexed.values())
            analyses = current.analyses.copy()
            for analysis in incoming.analyses:
                if analysis not in analyses:
                    analyses.append(analysis)
            updates.update(
                analyses=analyses,
                stopped=current.stopped or incoming.stopped,
                stop_reason=current.stop_reason or incoming.stop_reason,
                spent_requests=max(current.spent_requests, incoming.spent_requests),
                spent_seconds=max(current.spent_seconds, incoming.spent_seconds),
            )
            return AssessmentView.model_validate({**current.model_dump(), **updates})

        self._mutate(incoming.scope.assessment_id, merge)

    def import_records(
        self, assessment_id: str, payload: str | bytes, review: AttachmentReview
    ) -> AssessmentView:
        view = self.load(assessment_id)
        if view.stopped:
            raise ValueError("assessment is stopped; further collection/import is refused")
        try:
            artifacts, attachments = parse_import(view.scope, payload, review, self.redactor)
        except SensitiveDiscovery:
            return self.stop(
                assessment_id,
                (
                    "Unexpected sensitive information was discarded; stop collection "
                    "and prepare a private incident draft."
                ),
            )
        for artifact in artifacts:
            if artifact.artifact_id in attachments:
                path = self._safe_path(
                    self.directory
                    / assessment_id
                    / "attachments"
                    / (artifact.fields["screenshot.sha256"] + ".png")
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.read_bytes() != attachments[artifact.artifact_id]:
                    raise ValueError("existing screenshot differs from its content hash")
                if not path.exists():
                    path.write_bytes(attachments[artifact.artifact_id])
                artifacts[artifacts.index(artifact)] = EvidenceArtifact.model_validate(
                    {**artifact.model_dump(), "attachment_path": str(path)}
                )

        def append(current: AssessmentView) -> AssessmentView:
            if current.stopped:
                raise ValueError("assessment stopped while import was being reviewed")
            check_scope(current.scope, action="read")
            if {item.artifact_id for item in current.artifacts} & {
                item.artifact_id for item in artifacts
            }:
                raise ValueError("an imported artifact ID already exists")
            return AssessmentView.model_validate(
                {**current.model_dump(), "artifacts": [*current.artifacts, *artifacts]}
            )

        return self._mutate(assessment_id, append)

    def add_expectation(self, assessment_id: str, expectation: AccessExpectation) -> AssessmentView:
        expectation = AccessExpectation.model_validate(
            self.redactor.strings(expectation.model_dump(mode="json"))
        )

        def append(view: AssessmentView) -> AssessmentView:
            check_scope(view.scope, action="plan")
            if view.stopped:
                raise ValueError("assessment is stopped")
            if any(item.expectation_id == expectation.expectation_id for item in view.expectations):
                raise ValueError("expectation ID already exists")
            return AssessmentView.model_validate(
                {**view.model_dump(), "expectations": [*view.expectations, expectation]}
            )

        return self._mutate(assessment_id, append)

    def resolve_task(self, assessment_id: str, request: TaskResolveRequest) -> AssessmentAnswer:
        result: list[AssessmentAnswer] = []

        def append(view: AssessmentView) -> AssessmentView:
            task = interpret_prompt(
                request.prompt,
                assessment_id,
                tuple(request.evidence_ids),
                budget=request.budget,
                known_evidence_ids=tuple(item.artifact_id for item in view.artifacts),
                redactor=self.redactor,
            )
            if (
                task.budget.max_requests > view.scope.budget.max_requests
                or task.budget.max_seconds > view.scope.budget.max_seconds
            ):
                raise ValueError("task budget exceeds the explicit scope")
            if view.stopped and task.action != "report":
                raise ValueError(
                    "assessment is stopped; only a private incident/report draft is available"
                )
            answer = answer_task(view, task)
            result.append(answer)
            answers = view.answers if answer in view.answers else [*view.answers, answer]
            return AssessmentView.model_validate({**view.model_dump(), "answers": answers})

        self._mutate(assessment_id, append)
        return result[0]

    def add_comparison(
        self, assessment_id: str, request: ComparisonRequest
    ) -> ObservationComparison:
        result: list[ObservationComparison] = []

        def append(view: AssessmentView) -> AssessmentView:
            comparison = compare_observations(view, request)
            result.append(comparison)
            comparisons = (
                view.comparisons
                if comparison in view.comparisons
                else [*view.comparisons, comparison]
            )
            return AssessmentView.model_validate({**view.model_dump(), "comparisons": comparisons})

        self._mutate(assessment_id, append)
        return result[0]

    def stop(self, assessment_id: str, reason: str) -> AssessmentView:
        sanitized = self.redactor.text(reason)
        return self._mutate(
            assessment_id,
            lambda view: AssessmentView.model_validate(
                {**view.model_dump(), "stopped": True, "stop_reason": view.stop_reason or sanitized}
            ),
        )

    def charge_budget(
        self, assessment_id: str, *, requests: int = 0, seconds: float = 0
    ) -> AssessmentView:
        if isinstance(requests, bool) or not isinstance(requests, int) or requests < 0:
            raise ValueError("request accounting requires a nonnegative integer")
        if seconds < 0 or not float("-inf") < seconds < float("inf"):
            raise ValueError("seconds accounting requires a finite nonnegative number")

        def charge(view: AssessmentView) -> AssessmentView:
            if requests > 0:
                check_scope(view.scope)
            if view.stopped and requests > 0:
                raise ValueError("assessment is stopped; no further collection/analysis is allowed")
            if (
                view.spent_requests + requests > view.scope.budget.max_requests
                or view.spent_seconds + seconds > view.scope.budget.max_seconds
            ):
                raise ValueError("assessment lifetime budget is exhausted")
            return AssessmentView.model_validate(
                {
                    **view.model_dump(),
                    "spent_requests": view.spent_requests + requests,
                    "spent_seconds": view.spent_seconds + seconds,
                }
            )

        return self._mutate(assessment_id, charge)

    def report(self, assessment_id: str) -> ReportPreview:
        view = self.load(assessment_id)
        if "report" not in view.scope.allowed_actions and not view.stopped:
            raise ValueError("private reporting is outside the declared scope")
        return report_preview(view)

    def export_report(
        self, assessment_id: str, review: AttachmentReview, preview_sha256: str
    ) -> ReportPreview:
        AttachmentReview.model_validate(review.model_dump())
        if review.reviewed_at > datetime.now(UTC):
            raise ValueError("private export review cannot be in the future")
        preview = self.report(assessment_id)
        if preview.preview_sha256 != preview_sha256:
            raise ValueError("private report changed after human preview; review the current draft")
        path = self._safe_path(
            self.directory / assessment_id / "reports" / (digest(preview.markdown) + ".md")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(preview.markdown, encoding="utf-8", newline="\n")
        path.with_suffix(".json").write_text(
            preview.report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return ReportPreview.model_validate({**preview.model_dump(), "export_path": str(path)})

    def import_lab_records(
        self,
        assessment_id: str,
        result: ControlledHTTPResult,
        review: AttachmentReview,
        *,
        prepare_website: bool = False,
    ) -> AssessmentView:
        """Internal pinned-runner binding; deliberately unavailable to raw import endpoints."""
        from verification import lab

        result = ControlledHTTPResult.model_validate(result.model_dump())
        view = self.load(assessment_id)
        check_scope(view.scope, action="collect")
        if (
            view.stopped
            or view.scope.application_id != "owned-tandir"
            or result.runner_origin is None
        ):
            raise ValueError("trusted collection requires the active owned bundled-lab assessment")
        parsed = urlsplit(result.runner_origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path
        ):
            raise ValueError("trusted collection origin is not the verified loopback worker")
        if result.runner_manifest_sha256 != digest(lab.PIN.read_bytes()):
            raise ValueError("trusted collection manifest pin changed")
        runtime_scope = AssessmentScope.model_validate(
            {**view.scope.model_dump(), "origin": result.runner_origin}
        )
        review = AttachmentReview.model_validate(review.model_dump())
        artifacts = []
        binding = LabCollectionBinding(
            manifest_sha256=result.runner_manifest_sha256,
            scope_origin=view.scope.origin,
            runner_origin=result.runner_origin,
            preview_sha256=result.preview_sha256,
        )
        for record in result.records:
            artifact = sanitize_http_record(runtime_scope, record, review, self.redactor)
            artifacts.append(
                EvidenceArtifact.model_validate(
                    {**artifact.model_dump(), "trusted_lab_collection": binding}
                )
            )
        updated = AssessmentView.model_validate(
            {
                **view.model_dump(),
                "artifacts": [*view.artifacts, *artifacts],
                "analyses": [*view.analyses, json.loads(result.model_dump_json())],
                "stopped": view.stopped or result.stopped,
                "stop_reason": view.stop_reason or result.stop_reason,
            }
        )
        if prepare_website:
            from backend.website_workflow import prepared_website_comparisons

            updated = prepared_website_comparisons(updated, result.preview_sha256)
        self.save(updated)
        return self.load(assessment_id)

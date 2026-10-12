// Generated from backend JSON Schemas. Run pnpm contracts; never edit by hand.
// Structural types only. Backend validators remain authoritative for evidence and invariants.

// AccessExpectation.schema.json · SHA256 10e045d0af04e435de5a6c60b328e565139b697483961de8c12bd7b2328e7f8f
export namespace AccessExpectationSchema {
  export type AccessExpectation = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "expectation_id": string; readonly "object_id": string; readonly "path": string; readonly "statement": string; };
}
export type AccessExpectation = AccessExpectationSchema.AccessExpectation;

// AccessSite.schema.json · SHA256 d9b77567283b0283788c6140912a54f4c9a30517b14abcd92e599d24a2cfdeb6
export namespace AccessSiteSchema {
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
}
export type AccessSite = AccessSiteSchema.AccessSite;

// ApplicationMap.schema.json · SHA256 fe08d3b9369446438ecfd75565f2e3b870958904d1bf6f32036c59efa564b875
export namespace ApplicationMapSchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type EntryPoint = { readonly "framework": Framework; readonly "handler_symbol_id": string; readonly "id": string; readonly "kind": EntryPointKind; readonly "method"?: (string) | (null); readonly "route"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type EntryPointKind = "http_route" | "route_handler" | "server_action" | "page";
  export type Framework = "fastapi" | "nextjs";
  export type Guard = { readonly "canonical": string; readonly "confirmed"?: boolean; readonly "id": string; readonly "kind": GuardKind; readonly "mechanism": GuardMechanism; readonly "object"?: (string) | (null); readonly "role"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; readonly "subject"?: (string) | (null); readonly "via_symbol_id"?: (string) | (null); };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type GuardMechanism = "dependency" | "decorator" | "query_filter" | "comparison" | "helper_call" | "data_access_layer" | "router" | "proxy_matcher";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type Language = "python" | "typescript" | "tsx" | "javascript";
  export type LinkStatus = "resolved" | "inferred" | "unresolved";
  export type MapLink = { readonly "id": string; readonly "kind": "handler" | "call" | "reference" | "dependency" | "guard_candidate" | "access" | "may_check" | "proxy" | "client_props"; readonly "optimistic"?: boolean; readonly "reason": string; readonly "source": string; readonly "span": SourceSpan; readonly "status": LinkStatus; readonly "target": string; };
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Symbol = { readonly "id": string; readonly "kind": SymbolKind; readonly "language": Language; readonly "name": string; readonly "qualified_name": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type SymbolKind = "module" | "class" | "function" | "method" | "variable" | "component" | "type";
  export type UnknownTarget = { readonly "id": string; readonly "label": string; readonly "reason": string; readonly "span": SourceSpan; };
  export type ApplicationMap = { readonly "access_sites": ReadonlyArray<AccessSite>; readonly "entries": ReadonlyArray<EntryPoint>; readonly "guards": ReadonlyArray<Guard>; readonly "issues"?: ReadonlyArray<string>; readonly "limitations"?: ReadonlyArray<string>; readonly "links": ReadonlyArray<MapLink>; readonly "schema_version"?: 1; readonly "snapshot_id": string; readonly "symbols": ReadonlyArray<Symbol>; readonly "unknown_targets": ReadonlyArray<UnknownTarget>; };
}
export type ApplicationMap = ApplicationMapSchema.ApplicationMap;

// AssessmentAnswer.schema.json · SHA256 a2d60b43b348087f945f5854a01427436bef70af26d260362fa448df16e261c2
export namespace AssessmentAnswerSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentTask = { readonly "action": "compare" | "explain" | "missing" | "plan" | "report" | "analyze" | "source_review"; readonly "authorization_granted"?: false; readonly "budget"?: AssessmentBudget; readonly "clarification"?: (string) | (null); readonly "evidence_ids"?: ReadonlyArray<string>; readonly "focus"?: string; readonly "network_activity"?: false; readonly "prompt": string; readonly "status"?: "resolved" | "clarification_required" | "refused"; readonly "target_id": string; readonly "task_id": string; };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type AssessmentAnswer = { readonly "answer_id": string; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "generated_by"?: "deterministic" | "local_model"; readonly "task": AssessmentTask; readonly "text": string; readonly "unknowns"?: ReadonlyArray<string>; };
}
export type AssessmentAnswer = AssessmentAnswerSchema.AssessmentAnswer;

// AssessmentBudget.schema.json · SHA256 320ed22634575c8905bd61ad8c4f555f24a22d77adb28c069f62b9c9c80ed03a
export namespace AssessmentBudgetSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
}
export type AssessmentBudget = AssessmentBudgetSchema.AssessmentBudget;

// AssessmentChecklist.schema.json · SHA256 5bd28222286c7163f23d807dc3ac30419cf00589a0a2f27fb9e784e44ee657bb
export namespace AssessmentChecklistSchema {
  export type ChecklistItem = { readonly "account_ids": ReadonlyArray<string>; readonly "action"?: "read"; readonly "artifact_ids"?: ReadonlyArray<string>; readonly "check_id": string; readonly "expectation_id"?: (string) | (null); readonly "instructions": string; readonly "limitations"?: ReadonlyArray<string>; readonly "object_ids": ReadonlyArray<string>; readonly "path": string; readonly "status"?: "planned" | "observations_available" | "compared"; };
  export type AssessmentChecklist = { readonly "assessment_id": string; readonly "execution_status"?: "plan_only"; readonly "items": ReadonlyArray<ChecklistItem>; readonly "untested_paths": ReadonlyArray<string>; };
}
export type AssessmentChecklist = AssessmentChecklistSchema.AssessmentChecklist;

// AssessmentJob.schema.json · SHA256 1d9b7ca4daf54a6be8e6f0f09347fe5f1b4800e662a3045716bf24a78df3be48
export namespace AssessmentJobSchema {
  export type JsonValue = unknown;
  export type AssessmentJob = { readonly "action": "analyze" | "collect"; readonly "assessment_id": string; readonly "created_at": string; readonly "ended_at"?: (string) | (null); readonly "job_id": string; readonly "message": string; readonly "result"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "state": "queued" | "running" | "completed" | "canceled" | "failed"; };
}
export type AssessmentJob = AssessmentJobSchema.AssessmentJob;

// AssessmentList.schema.json · SHA256 e93ff1cc3d42bf853ccfcb384ac2d0c5f152fc07ccf582bccc51eb78a59ea80e
export namespace AssessmentListSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentScope = { readonly "accounts": ReadonlyArray<TestAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "compare" | "plan" | "report" | "analyze" | "collect" | "authenticate" | "create_synthetic">; readonly "allowed_paths": ReadonlyArray<string>; readonly "application_id": string; readonly "application_name": string; readonly "assessment_id": string; readonly "authority": ScopeAuthority; readonly "budget"?: AssessmentBudget; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "origin": string; readonly "scope_id": string; readonly "stop_conditions": ReadonlyArray<string>; readonly "synthetic_objects"?: ReadonlyArray<SyntheticObject>; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SyntheticObject = { readonly "kind": string; readonly "object_id": string; readonly "owner_account_id": string; readonly "synthetic"?: true; readonly "synthetic_marker"?: (string) | (null); };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type AssessmentList = { readonly "assessments": ReadonlyArray<AssessmentScope>; };
}
export type AssessmentList = AssessmentListSchema.AssessmentList;

// AssessmentReport.schema.json · SHA256 fc4e66e3327046509b7dae387b616b8a0db2c314964af309303356db3056bc62
export namespace AssessmentReportSchema {
  export type AccessExpectation = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "expectation_id": string; readonly "object_id": string; readonly "path": string; readonly "statement": string; };
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type ComparisonRequest = { readonly "control_artifact_id"?: (string) | (null); readonly "expectation_id"?: (string) | (null); readonly "left_artifact_id": string; readonly "right_artifact_id": string; };
  export type EvidenceArtifact = { readonly "artifact_id": string; readonly "assessment_id": string; readonly "attachment_path"?: (string) | (null); readonly "collected_at": string; readonly "context"?: (ObservationContext) | (null); readonly "execution_status"?: "imported"; readonly "fields": Readonly<Record<string, string>>; readonly "imported_at": string; readonly "kind": "request_response" | "note" | "screenshot"; readonly "provenance": string; readonly "review": AttachmentReview; readonly "sha256": string; readonly "trusted_lab_collection"?: (LabCollectionBinding) | (null); };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type LabCollectionBinding = { readonly "manifest_sha256": string; readonly "preview_sha256": string; readonly "runner_origin": string; readonly "scope_origin": string; };
  export type ObservationComparison = { readonly "alternative_explanations"?: ReadonlyArray<string>; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "comparison_id": string; readonly "conclusion": "candidate" | "rejected" | "inconclusive"; readonly "execution_status"?: "imported"; readonly "missing_evidence"?: ReadonlyArray<string>; readonly "request": ComparisonRequest; readonly "summary": string; };
  export type ObservationContext = { readonly "account_id": string; readonly "object_id": string; readonly "request_context_id": string; readonly "session_context_id": string; };
  export type ReportClaim = { readonly "citations": ReadonlyArray<EvidenceCitation>; readonly "text": string; };
  export type AssessmentReport = { readonly "affected_endpoints": ReadonlyArray<string>; readonly "assessment_id": string; readonly "claims": ReadonlyArray<ReportClaim>; readonly "comparisons": ReadonlyArray<ObservationComparison>; readonly "confidentiality"?: "private_local"; readonly "description": string; readonly "dismissed_leads": ReadonlyArray<string>; readonly "evidence": ReadonlyArray<EvidenceArtifact>; readonly "expected_behavior": ReadonlyArray<AccessExpectation>; readonly "human_preview_required"?: true; readonly "impact": string; readonly "limitations": ReadonlyArray<string>; readonly "methodology": ReadonlyArray<string>; readonly "mitigation": ReadonlyArray<string>; readonly "runtime_verification"?: "not_attempted"; readonly "safe_reproduction": ReadonlyArray<string>; readonly "tested_coverage": ReadonlyArray<string>; readonly "title": string; readonly "tools_and_models": ReadonlyArray<string>; readonly "untested_coverage": ReadonlyArray<string>; };
}
export type AssessmentReport = AssessmentReportSchema.AssessmentReport;

// AssessmentScope.schema.json · SHA256 5a6cf23ee296e4886d5036f479373a6ee70ee7325956b68d2042b5bf06805117
export namespace AssessmentScopeSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SyntheticObject = { readonly "kind": string; readonly "object_id": string; readonly "owner_account_id": string; readonly "synthetic"?: true; readonly "synthetic_marker"?: (string) | (null); };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type AssessmentScope = { readonly "accounts": ReadonlyArray<TestAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "compare" | "plan" | "report" | "analyze" | "collect" | "authenticate" | "create_synthetic">; readonly "allowed_paths": ReadonlyArray<string>; readonly "application_id": string; readonly "application_name": string; readonly "assessment_id": string; readonly "authority": ScopeAuthority; readonly "budget"?: AssessmentBudget; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "origin": string; readonly "scope_id": string; readonly "stop_conditions": ReadonlyArray<string>; readonly "synthetic_objects"?: ReadonlyArray<SyntheticObject>; };
}
export type AssessmentScope = AssessmentScopeSchema.AssessmentScope;

// AssessmentTask.schema.json · SHA256 1c9f392567e434c043b45574cd724e9c9dff2a0e329bedb3c97056491902bd60
export namespace AssessmentTaskSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentTask = { readonly "action": "compare" | "explain" | "missing" | "plan" | "report" | "analyze" | "source_review"; readonly "authorization_granted"?: false; readonly "budget"?: AssessmentBudget; readonly "clarification"?: (string) | (null); readonly "evidence_ids"?: ReadonlyArray<string>; readonly "focus"?: string; readonly "network_activity"?: false; readonly "prompt": string; readonly "status"?: "resolved" | "clarification_required" | "refused"; readonly "target_id": string; readonly "task_id": string; };
}
export type AssessmentTask = AssessmentTaskSchema.AssessmentTask;

// AssessmentView.schema.json · SHA256 b149d1fc617b4e7af8513f0f4adb44dcc00849f82e48d753cdedd1f0bb4b33fa
export namespace AssessmentViewSchema {
  export type AccessExpectation = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "expectation_id": string; readonly "object_id": string; readonly "path": string; readonly "statement": string; };
  export type AssessmentAnswer = { readonly "answer_id": string; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "generated_by"?: "deterministic" | "local_model"; readonly "task": AssessmentTask; readonly "text": string; readonly "unknowns"?: ReadonlyArray<string>; };
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentScope = { readonly "accounts": ReadonlyArray<TestAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "compare" | "plan" | "report" | "analyze" | "collect" | "authenticate" | "create_synthetic">; readonly "allowed_paths": ReadonlyArray<string>; readonly "application_id": string; readonly "application_name": string; readonly "assessment_id": string; readonly "authority": ScopeAuthority; readonly "budget"?: AssessmentBudget; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "origin": string; readonly "scope_id": string; readonly "stop_conditions": ReadonlyArray<string>; readonly "synthetic_objects"?: ReadonlyArray<SyntheticObject>; };
  export type AssessmentTask = { readonly "action": "compare" | "explain" | "missing" | "plan" | "report" | "analyze" | "source_review"; readonly "authorization_granted"?: false; readonly "budget"?: AssessmentBudget; readonly "clarification"?: (string) | (null); readonly "evidence_ids"?: ReadonlyArray<string>; readonly "focus"?: string; readonly "network_activity"?: false; readonly "prompt": string; readonly "status"?: "resolved" | "clarification_required" | "refused"; readonly "target_id": string; readonly "task_id": string; };
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type ComparisonRequest = { readonly "control_artifact_id"?: (string) | (null); readonly "expectation_id"?: (string) | (null); readonly "left_artifact_id": string; readonly "right_artifact_id": string; };
  export type EvidenceArtifact = { readonly "artifact_id": string; readonly "assessment_id": string; readonly "attachment_path"?: (string) | (null); readonly "collected_at": string; readonly "context"?: (ObservationContext) | (null); readonly "execution_status"?: "imported"; readonly "fields": Readonly<Record<string, string>>; readonly "imported_at": string; readonly "kind": "request_response" | "note" | "screenshot"; readonly "provenance": string; readonly "review": AttachmentReview; readonly "sha256": string; readonly "trusted_lab_collection"?: (LabCollectionBinding) | (null); };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type JsonValue = unknown;
  export type LabCollectionBinding = { readonly "manifest_sha256": string; readonly "preview_sha256": string; readonly "runner_origin": string; readonly "scope_origin": string; };
  export type ObservationComparison = { readonly "alternative_explanations"?: ReadonlyArray<string>; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "comparison_id": string; readonly "conclusion": "candidate" | "rejected" | "inconclusive"; readonly "execution_status"?: "imported"; readonly "missing_evidence"?: ReadonlyArray<string>; readonly "request": ComparisonRequest; readonly "summary": string; };
  export type ObservationContext = { readonly "account_id": string; readonly "object_id": string; readonly "request_context_id": string; readonly "session_context_id": string; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SyntheticObject = { readonly "kind": string; readonly "object_id": string; readonly "owner_account_id": string; readonly "synthetic"?: true; readonly "synthetic_marker"?: (string) | (null); };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type AssessmentView = { readonly "analyses"?: ReadonlyArray<Readonly<Record<string, JsonValue>>>; readonly "answers"?: ReadonlyArray<AssessmentAnswer>; readonly "artifacts"?: ReadonlyArray<EvidenceArtifact>; readonly "comparisons"?: ReadonlyArray<ObservationComparison>; readonly "expectations"?: ReadonlyArray<AccessExpectation>; readonly "scope": AssessmentScope; readonly "spent_requests"?: number; readonly "spent_seconds"?: number; readonly "stop_reason"?: (string) | (null); readonly "stopped"?: boolean; };
}
export type AssessmentView = AssessmentViewSchema.AssessmentView;

// AttachmentReview.schema.json · SHA256 b2e39c44cf25d9240898a3fc6dd178f9c14ebfa728156bf36ed71f7d6a0b0018
export namespace AttachmentReviewSchema {
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
}
export type AttachmentReview = AttachmentReviewSchema.AttachmentReview;

// BoundPolicy.schema.json · SHA256 bd9eae7f90a11126aabaf8c47d4ae2e2e8c2a0e3375dd146114c64f184ccedd9
export namespace BoundPolicySchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
}
export type BoundPolicy = BoundPolicySchema.BoundPolicy;

// CapabilityTable.schema.json · SHA256 688bfef3bb910d6ae5407e76b878444ab23cdfee9d1a699503c912dd234a77be
export namespace CapabilityTableSchema {
  export type CapabilityEvidence = { readonly "current_engine_acceptance"?: false; readonly "record": string; readonly "scope": string; readonly "sha256": string; };
  export type CapabilityRow = { readonly "category": "language" | "framework" | "family"; readonly "indexed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "indexed_units"?: (number) | (null); readonly "investigated"?: false; readonly "name": string; readonly "parsed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "parsed_units"?: (number) | (null); readonly "reason": string; readonly "runtime_testable"?: false; readonly "units"?: (number) | (null); readonly "workflow_implemented": boolean; };
  export type CapabilityTable = { readonly "evidence": ReadonlyArray<CapabilityEvidence>; readonly "quality_note": string; readonly "registry_sha256": string; readonly "rows": ReadonlyArray<CapabilityRow>; readonly "runtime_note": string; readonly "schema_version"?: 1; readonly "snapshot_id"?: (string) | (null); };
}
export type CapabilityTable = CapabilityTableSchema.CapabilityTable;

// CaseDetail.schema.json · SHA256 71bcef29b54e4bd01340ae7e3386fa471e5e9b40b8971dcb49a8a6b8c3f456c7
export namespace CaseDetailSchema {
  export type Access = "allowed" | "denied";
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
  export type ChallengeCheck = { readonly "exhibit_tag"?: (string) | (null); readonly "found": boolean; readonly "item": string; readonly "searched": string; };
  export type ChangeStatus = "proposed" | "replayed_fixed" | "replayed_not_fixed" | "replay_failed";
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type DispositionDecision = { readonly "actor": string; readonly "disposition": Disposition; readonly "expected_version": number; readonly "finding_id": string; readonly "original_finding_sha256": string; readonly "previous_disposition": Disposition; readonly "reason": string; readonly "recorded_at": string; readonly "resolution_commit"?: (string) | (null); readonly "run_id": string; readonly "snapshot_id": string; readonly "version": number; };
  export type EntryPoint = { readonly "framework": Framework; readonly "handler_symbol_id": string; readonly "id": string; readonly "kind": EntryPointKind; readonly "method"?: (string) | (null); readonly "route"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type EntryPointKind = "http_route" | "route_handler" | "server_action" | "page";
  export type EvidenceStrength = "complete" | "partial" | "thin";
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type Finding = { readonly "checks"?: ReadonlyArray<ChallengeCheck>; readonly "conclusion": Conclusion; readonly "cwe": ReadonlyArray<number>; readonly "display_id": string; readonly "disposition"?: Disposition; readonly "disposition_reason"?: (string) | (null); readonly "exhibits": ReadonlyArray<Exhibit>; readonly "family": Family; readonly "flow"?: ReadonlyArray<FlowStep>; readonly "gaps"?: ReadonlyArray<string>; readonly "id": string; readonly "lede": string; readonly "peer_group_id"?: (string) | (null); readonly "policy_basis"?: ReadonlyArray<BoundPolicy>; readonly "probe_run_ids"?: ReadonlyArray<string>; readonly "question_ids"?: ReadonlyArray<string>; readonly "run_id": string; readonly "runtime_verification"?: RuntimeVerification; readonly "severity": Severity; readonly "severity_rationale": string; readonly "snapshot_id": string; readonly "strength": EvidenceStrength; readonly "suggested_change_id"?: (string) | (null); readonly "title": string; readonly "unknowns"?: ReadonlyArray<string>; };
  export type FixProposal = { readonly "adapter_manifest_sha256"?: (string) | (null); readonly "change"?: (SuggestedChange) | (null); readonly "finding_id": string; readonly "id": string; readonly "probe_reason": string; readonly "probe_spec"?: (ProbeSpec) | (null); readonly "probe_status"?: "available" | "unavailable"; readonly "reason": string; readonly "snapshot_id": string; readonly "status": "proposed" | "refused" | "unavailable"; };
  export type FlowStep = { readonly "exhibit_tag": string; readonly "label": string; };
  export type Framework = "fastapi" | "nextjs";
  export type Guard = { readonly "canonical": string; readonly "confirmed"?: boolean; readonly "id": string; readonly "kind": GuardKind; readonly "mechanism": GuardMechanism; readonly "object"?: (string) | (null); readonly "role"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; readonly "subject"?: (string) | (null); readonly "via_symbol_id"?: (string) | (null); };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type GuardMechanism = "dependency" | "decorator" | "query_filter" | "comparison" | "helper_call" | "data_access_layer" | "router" | "proxy_matcher";
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type JsonValue = unknown;
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PeerColumn = { readonly "applied_site_ids": ReadonlyArray<string>; readonly "key": string; readonly "label": string; };
  export type PeerComparison = { readonly "finding_id": string; readonly "group": PeerGroup; readonly "limitations"?: ReadonlyArray<string>; readonly "question_id": string; readonly "rows": ReadonlyArray<PeerRow>; readonly "subject_site_id": string; };
  export type PeerDeviation = { readonly "missing": string; readonly "peers_applying": number; readonly "peers_total": number; readonly "site_id": string; };
  export type PeerExclusion = { readonly "reason": string; readonly "site_id": string; };
  export type PeerGroup = { readonly "columns": ReadonlyArray<PeerColumn>; readonly "deviations"?: ReadonlyArray<PeerDeviation>; readonly "excluded"?: ReadonlyArray<PeerExclusion>; readonly "id": string; readonly "min_peers"?: number; readonly "min_share"?: number; readonly "resource": string; readonly "site_ids": ReadonlyArray<string>; readonly "snapshot_id": string; };
  export type PeerRow = { readonly "entry": EntryPoint; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "exclusion"?: (string) | (null); readonly "guards"?: ReadonlyArray<Guard>; readonly "issues"?: ReadonlyArray<string>; readonly "site": AccessSite; };
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type ProbeOutcome = "reproduced" | "not_reproduced" | "fixed" | "not_fixed" | "inconclusive";
  export type ProbeRun = { readonly "finding_id": string; readonly "finished_at": string; readonly "id": string; readonly "outcome": ProbeOutcome; readonly "runner": RunnerKind; readonly "runner_manifest_sha256": string; readonly "snapshot_id": string; readonly "snapshot_role": SnapshotRole; readonly "started_at": string; readonly "steps": ReadonlyArray<ProbeStep>; };
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
  export type ProbeStep = { readonly "error"?: (string) | (null); readonly "expected_if_safe": Access; readonly "marker_present"?: (boolean) | (null); readonly "method": string; readonly "path": string; readonly "principal": string; readonly "role": StepRole; readonly "status"?: (number) | (null); };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type RunnerKind = "bundled_lab" | "windows_sandbox" | "docker";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SnapshotRole = "vulnerable" | "patched";
  export type SourceEdit = { readonly "action": "replace" | "insert_before" | "insert_after" | "delete"; readonly "code": string; readonly "file_sha256": string; readonly "source": SourceSpan; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type StepRole = "setup" | "attack" | "control";
  export type SuggestedChange = { readonly "diff": string; readonly "files": ReadonlyArray<string>; readonly "finding_id": string; readonly "id": string; readonly "intent": string; readonly "replay_probe_run_ids"?: ReadonlyArray<string>; readonly "snapshot_id"?: (string) | (null); readonly "source_edits"?: ReadonlyArray<SourceEdit>; readonly "source_scope"?: (SourceSpan) | (null); readonly "status"?: ChangeStatus; };
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type CaseDetail = { readonly "disposition_history"?: ReadonlyArray<DispositionDecision>; readonly "finding": Finding; readonly "limitations": ReadonlyArray<string>; readonly "peer_comparison"?: (PeerComparison) | ("not_recorded"); readonly "probe_runs": ReadonlyArray<ProbeRun>; readonly "proposal"?: (FixProposal) | (null); readonly "run": ReviewRun; readonly "suggested_change"?: (SuggestedChange) | (null); };
}
export type CaseDetail = CaseDetailSchema.CaseDetail;

// ChatAsk.schema.json · SHA256 4a951a57c0c62791beb3e4fbaa595032a0cd9d576478e62ac6454d8b566950a0
export namespace ChatAskSchema {
  export type ChatAsk = { readonly "choice"?: ("general_question" | "creative_writing" | "explain_result" | "general_and_result" | "review_folder" | "test_website" | "about_plumb" | "unclear") | (null); readonly "max_seconds"?: number; readonly "profile"?: string; readonly "prompt": string; };
}
export type ChatAsk = ChatAskSchema.ChatAsk;

// ChatCreate.schema.json · SHA256 63a6966fad8ae21f8684b777bd67f71fc0f65f0f8eb5f57e68e77f1f0e48c2f1
export namespace ChatCreateSchema {
  export type ChatCreate = { readonly "target_id"?: (string) | (null); readonly "target_kind"?: ("inspection" | "review" | "assessment" | "website") | (null); };
}
export type ChatCreate = ChatCreateSchema.ChatCreate;

// ChatSelect.schema.json · SHA256 c2b2ce58ae2a78be9f2f3d49c0c7e852adcb2d434426d0a6dbb7f09b0f4fd123
export namespace ChatSelectSchema {
  export type ChatSelect = { readonly "target_id"?: (string) | (null); readonly "target_kind"?: ("inspection" | "review" | "assessment" | "website") | (null); };
}
export type ChatSelect = ChatSelectSchema.ChatSelect;

// ChatView.schema.json · SHA256 f8094c8d5ba7197c0bb7a8d7f5dcbd1773776f560778d7250d7a31564c1d9b7a
export namespace ChatViewSchema {
  export type ChatChoice = { readonly "intent": "general_question" | "creative_writing" | "explain_result" | "general_and_result" | "review_folder" | "test_website" | "about_plumb" | "unclear"; readonly "label": string; };
  export type ChatPart = { readonly "basis": string; readonly "complete"?: boolean; readonly "evidence"?: ReadonlyArray<ConversationEvidence>; readonly "guidance_card"?: (string) | (null); readonly "kind": "general" | "guidance" | "cited" | "notice"; readonly "text": string; readonly "unknowns"?: ReadonlyArray<string>; };
  export type ChatTask = { readonly "authorization_granted"?: false; readonly "folder"?: (string) | (null); readonly "kind": "inspect_folder" | "website_setup" | "choose_result"; readonly "missing"?: ReadonlyArray<string>; readonly "ready": boolean; readonly "started"?: false; readonly "steps"?: ReadonlyArray<string>; readonly "summary": string; readonly "url"?: (string) | (null); };
  export type ChatTurn = { readonly "actions_executed"?: false; readonly "authorization_granted"?: false; readonly "choices"?: ReadonlyArray<ChatChoice>; readonly "finding_created"?: false; readonly "intent": "general_question" | "creative_writing" | "explain_result" | "general_and_result" | "review_folder" | "test_website" | "about_plumb" | "unclear"; readonly "intent_rung": "code" | "model" | "model_reordered" | "user" | "stop"; readonly "interpretation": string; readonly "limits": string; readonly "model_requests"?: number; readonly "model_seconds"?: number; readonly "parts"?: ReadonlyArray<ChatPart>; readonly "prompt": string; readonly "task"?: (ChatTask) | (null); };
  export type ConversationEvidence = { readonly "label": string; readonly "model_quote"?: (string) | (null); readonly "observation"?: (EvidenceCitation) | (null); readonly "quote": string; readonly "reference_id": string; readonly "source"?: (SourceSpan) | (null); };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type ChatView = { readonly "chat_id": string; readonly "confidentiality"?: "private_local"; readonly "limits"?: string; readonly "message"?: string; readonly "progress"?: (string) | (null); readonly "state"?: "idle" | "running" | "completed" | "failed" | "canceled"; readonly "target_id"?: (string) | (null); readonly "target_kind"?: ("inspection" | "review" | "assessment" | "website") | (null); readonly "target_label"?: (string) | (null); readonly "turns"?: ReadonlyArray<ChatTurn>; };
}
export type ChatView = ChatViewSchema.ChatView;

// CitedExcerpt.schema.json · SHA256 38668ddb0c2caa4c5933c8e898c9799c4302129dd76e3dabb6e2d0bc90bcc8c5
export namespace CitedExcerptSchema {
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type CitedExcerpt = { readonly "comments_are_not_evidence"?: true; readonly "end_line": number; readonly "exhibit": Exhibit; readonly "finding_id": string; readonly "lines": ReadonlyArray<string>; readonly "next_offset"?: (number) | (null); readonly "run_id": string; readonly "snapshot_id": string; readonly "start_line": number; readonly "text_is_redacted"?: true; };
}
export type CitedExcerpt = CitedExcerptSchema.CitedExcerpt;

// ComparisonRequest.schema.json · SHA256 483de2961c1509849b2097e7564a1ff760300b024d4f543628e96ef18a0c7d9c
export namespace ComparisonRequestSchema {
  export type ComparisonRequest = { readonly "control_artifact_id"?: (string) | (null); readonly "expectation_id"?: (string) | (null); readonly "left_artifact_id": string; readonly "right_artifact_id": string; };
}
export type ComparisonRequest = ComparisonRequestSchema.ComparisonRequest;

// ControlledHTTPAction.schema.json · SHA256 c741923d8891a30d1a4908872be94748e529974442edbfcb467fa4f96b4b5073
export namespace ControlledHTTPActionSchema {
  export type JsonValue = unknown;
  export type ControlledHTTPAction = { readonly "account_id": ("alice" | "bob") | (null); readonly "action_id": string; readonly "body_preview"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "max_attempts"?: number; readonly "method": "GET" | "POST"; readonly "path": string; readonly "purpose": "readiness" | "authenticate" | "create_synthetic" | "read"; readonly "state_change": boolean; };
}
export type ControlledHTTPAction = ControlledHTTPActionSchema.ControlledHTTPAction;

// ControlledHTTPPermission.schema.json · SHA256 98b119c427a0ea5d89ce524b3c1ded7f06d6525140b307faa12171aeec556401
export namespace ControlledHTTPPermissionSchema {
  export type ControlledHTTPPermission = { readonly "approved_action_ids": ReadonlyArray<string>; readonly "approved_by": string; readonly "expires_at": string; readonly "granted_at": string; readonly "preview_sha256": string; readonly "reviewed_preview": true; };
}
export type ControlledHTTPPermission = ControlledHTTPPermissionSchema.ControlledHTTPPermission;

// ControlledHTTPPreview.schema.json · SHA256 4a9e88848a6ae791b57a1b52ab843d5a48110e3c122658beb107ea5763f1df97
export namespace ControlledHTTPPreviewSchema {
  export type Access = "allowed" | "denied";
  export type ControlledHTTPAction = { readonly "account_id": ("alice" | "bob") | (null); readonly "action_id": string; readonly "body_preview"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "max_attempts"?: number; readonly "method": "GET" | "POST"; readonly "path": string; readonly "purpose": "readiness" | "authenticate" | "create_synthetic" | "read"; readonly "state_change": boolean; };
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type JsonValue = unknown;
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
  export type StepRole = "setup" | "attack" | "control";
  export type ControlledHTTPPreview = { readonly "actions": ReadonlyArray<ControlledHTTPAction>; readonly "assessment_id": string; readonly "control_spec"?: (ProbeSpec) | (null); readonly "created_at": string; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "max_requests": number; readonly "max_response_bytes"?: number; readonly "max_seconds": number; readonly "max_total_bytes"?: number; readonly "preview_id": string; readonly "runner"?: "hash_pinned_owned_tandir"; readonly "runner_manifest_sha256": string; readonly "scope_sha256": string; readonly "spec": ProbeSpec; readonly "synthetic_object_id": string; };
}
export type ControlledHTTPPreview = ControlledHTTPPreviewSchema.ControlledHTTPPreview;

// ControlledHTTPResult.schema.json · SHA256 962f9ba937ee8ca94368a81daf6eed4a6e50dc6d7e334ea906d0aa31a8512d83
export namespace ControlledHTTPResultSchema {
  export type HTTPActionProgress = { readonly "action_id": string; readonly "artifact_ids"?: ReadonlyArray<string>; readonly "attempts"?: number; readonly "completed"?: boolean; readonly "missing_evidence"?: ReadonlyArray<string>; };
  export type JsonValue = unknown;
  export type ControlledHTTPResult = { readonly "action_progress"?: ReadonlyArray<HTTPActionProgress>; readonly "bytes_received"?: number; readonly "execution_status"?: "collected_owned_lab"; readonly "preview_id": string; readonly "preview_sha256": string; readonly "records"?: ReadonlyArray<Readonly<Record<string, JsonValue>>>; readonly "requests_used": number; readonly "runner_manifest_sha256": string; readonly "runner_origin"?: (string) | (null); readonly "runtime_verification"?: "not_attempted"; readonly "seconds": number; readonly "stop_reason"?: (string) | (null); readonly "stopped": boolean; };
}
export type ControlledHTTPResult = ControlledHTTPResultSchema.ControlledHTTPResult;

// ConversationAsk.schema.json · SHA256 993889fbad3f3105013039299d50d8f47d160274ce8e5db9a87cc25b6e19c0cd
export namespace ConversationAskSchema {
  export type ConversationAsk = { readonly "max_seconds"?: number; readonly "profile"?: string; readonly "prompt": string; };
}
export type ConversationAsk = ConversationAskSchema.ConversationAsk;

// ConversationCreate.schema.json · SHA256 f2e94287a0be61f51fd4e52543c689fc5719c5c654efd3e856ac5702d04d31d2
export namespace ConversationCreateSchema {
  export type ConversationCreate = { readonly "target_id": string; readonly "target_kind": "inspection" | "review" | "assessment"; };
}
export type ConversationCreate = ConversationCreateSchema.ConversationCreate;

// ConversationView.schema.json · SHA256 3320745825634b6a7b5a5c947c1edf3ea6b3df685f5f2e5ac3d6d7f11aed47c1
export namespace ConversationViewSchema {
  export type ConversationEvidence = { readonly "label": string; readonly "model_quote"?: (string) | (null); readonly "observation"?: (EvidenceCitation) | (null); readonly "quote": string; readonly "reference_id": string; readonly "source"?: (SourceSpan) | (null); };
  export type ConversationTurn = { readonly "actions_executed"?: false; readonly "answer": string; readonly "authorization_granted"?: false; readonly "evidence": ReadonlyArray<ConversationEvidence>; readonly "evidence_sha256": string; readonly "generated_by": "local_model" | "unresolved"; readonly "prompt": string; readonly "unknowns": ReadonlyArray<string>; readonly "verdict_changed"?: false; };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type ConversationView = { readonly "confidentiality"?: "private_local"; readonly "conversation_id": string; readonly "message"?: string; readonly "state"?: "idle" | "running" | "completed" | "failed" | "canceled"; readonly "target_id": string; readonly "target_kind": "inspection" | "review" | "assessment"; readonly "turns"?: ReadonlyArray<ConversationTurn>; };
}
export type ConversationView = ConversationViewSchema.ConversationView;

// DispositionDecision.schema.json · SHA256 5c30c5b3d436b989c4378b52ac0820b29bb3ec8aa06aa8a0e3b790c79021951e
export namespace DispositionDecisionSchema {
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type DispositionDecision = { readonly "actor": string; readonly "disposition": Disposition; readonly "expected_version": number; readonly "finding_id": string; readonly "original_finding_sha256": string; readonly "previous_disposition": Disposition; readonly "reason": string; readonly "recorded_at": string; readonly "resolution_commit"?: (string) | (null); readonly "run_id": string; readonly "snapshot_id": string; readonly "version": number; };
}
export type DispositionDecision = DispositionDecisionSchema.DispositionDecision;

// DispositionUpdate.schema.json · SHA256 8a507048da703d154c6553012cc9d42b0e68be96f811e024d710f07d62c3a597
export namespace DispositionUpdateSchema {
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type DispositionUpdate = { readonly "actor": string; readonly "disposition": Disposition; readonly "expected_version": number; readonly "previous_disposition": Disposition; readonly "reason": string; readonly "resolution_commit"?: (string) | (null); readonly "snapshot_id": string; };
}
export type DispositionUpdate = DispositionUpdateSchema.DispositionUpdate;

// EntryPoint.schema.json · SHA256 7e495f285682aeaa8dd940ace6ba4c8a1bf44ddcc172c7b555578a522207365d
export namespace EntryPointSchema {
  export type EntryPointKind = "http_route" | "route_handler" | "server_action" | "page";
  export type Framework = "fastapi" | "nextjs";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type EntryPoint = { readonly "framework": Framework; readonly "handler_symbol_id": string; readonly "id": string; readonly "kind": EntryPointKind; readonly "method"?: (string) | (null); readonly "route"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; };
}
export type EntryPoint = EntryPointSchema.EntryPoint;

// EvidenceArtifact.schema.json · SHA256 3fde2587a91d43f2600d9c2d5c80f98b56ad386c10e82453dae13a6e382dacdc
export namespace EvidenceArtifactSchema {
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type LabCollectionBinding = { readonly "manifest_sha256": string; readonly "preview_sha256": string; readonly "runner_origin": string; readonly "scope_origin": string; };
  export type ObservationContext = { readonly "account_id": string; readonly "object_id": string; readonly "request_context_id": string; readonly "session_context_id": string; };
  export type EvidenceArtifact = { readonly "artifact_id": string; readonly "assessment_id": string; readonly "attachment_path"?: (string) | (null); readonly "collected_at": string; readonly "context"?: (ObservationContext) | (null); readonly "execution_status"?: "imported"; readonly "fields": Readonly<Record<string, string>>; readonly "imported_at": string; readonly "kind": "request_response" | "note" | "screenshot"; readonly "provenance": string; readonly "review": AttachmentReview; readonly "sha256": string; readonly "trusted_lab_collection"?: (LabCollectionBinding) | (null); };
}
export type EvidenceArtifact = EvidenceArtifactSchema.EvidenceArtifact;

// EvidenceCitation.schema.json · SHA256 6186f62ab7710e5be308d16cdf1d0ce47ff95e7e03b7e833af390568a1d41b4d
export namespace EvidenceCitationSchema {
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
}
export type EvidenceCitation = EvidenceCitationSchema.EvidenceCitation;

// EvidenceImportRequest.schema.json · SHA256 d726238ccd403d1359dd9ccc15f89d803bd3d3fc64c9e8903f85cbcce8453f98
export namespace EvidenceImportRequestSchema {
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type EvidenceImportRequest = { readonly "payload": string; readonly "review": AttachmentReview; };
}
export type EvidenceImportRequest = EvidenceImportRequestSchema.EvidenceImportRequest;

// Finding.schema.json · SHA256 edd43060203b98b121b01c285e61a683f3bb60a109303f722c216c6fdbba3ae5
export namespace FindingSchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
  export type ChallengeCheck = { readonly "exhibit_tag"?: (string) | (null); readonly "found": boolean; readonly "item": string; readonly "searched": string; };
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type EvidenceStrength = "complete" | "partial" | "thin";
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type FlowStep = { readonly "exhibit_tag": string; readonly "label": string; };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Finding = { readonly "checks"?: ReadonlyArray<ChallengeCheck>; readonly "conclusion": Conclusion; readonly "cwe": ReadonlyArray<number>; readonly "display_id": string; readonly "disposition"?: Disposition; readonly "disposition_reason"?: (string) | (null); readonly "exhibits": ReadonlyArray<Exhibit>; readonly "family": Family; readonly "flow"?: ReadonlyArray<FlowStep>; readonly "gaps"?: ReadonlyArray<string>; readonly "id": string; readonly "lede": string; readonly "peer_group_id"?: (string) | (null); readonly "policy_basis"?: ReadonlyArray<BoundPolicy>; readonly "probe_run_ids"?: ReadonlyArray<string>; readonly "question_ids"?: ReadonlyArray<string>; readonly "run_id": string; readonly "runtime_verification"?: RuntimeVerification; readonly "severity": Severity; readonly "severity_rationale": string; readonly "snapshot_id": string; readonly "strength": EvidenceStrength; readonly "suggested_change_id"?: (string) | (null); readonly "title": string; readonly "unknowns"?: ReadonlyArray<string>; };
}
export type Finding = FindingSchema.Finding;

// FindingList.schema.json · SHA256 1b23fc985f0d44433553db7a812fed6a0a86f839bd372cb1bd6e925d87cf3810
export namespace FindingListSchema {
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type FindingRow = { readonly "conclusion": Conclusion; readonly "display_id": string; readonly "disposition": Disposition; readonly "family": Family; readonly "id": string; readonly "location": (SourceSpan) | (null); readonly "runtime_verification": RuntimeVerification; readonly "severity": Severity; readonly "title": string; };
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type SecuritySignal = { readonly "advisory_id"?: (string) | (null); readonly "category": "secret" | "configuration" | "dependency"; readonly "ecosystem"?: ("npm" | "PyPI") | (null); readonly "fingerprint"?: (string) | (null); readonly "id": string; readonly "limitations": ReadonlyArray<string>; readonly "package"?: (string) | (null); readonly "rule_id": string; readonly "rule_version": string; readonly "source": SourceSpan; readonly "status": "observed" | "unknown"; readonly "summary": string; readonly "version"?: (string) | (null); };
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SignalSet = { readonly "limitations"?: ReadonlyArray<string>; readonly "pack_date"?: (string) | (null); readonly "pack_sha256"?: (string) | (null); readonly "pack_source"?: (string) | (null); readonly "run_id": string; readonly "signals"?: ReadonlyArray<SecuritySignal>; readonly "snapshot_id": string; readonly "status": "ok" | "partial" | "not_run"; readonly "tool_version": string; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type FindingList = { readonly "counts": Readonly<Record<string, number>>; readonly "findings": ReadonlyArray<FindingRow>; readonly "limitations": ReadonlyArray<string>; readonly "next_offset": (number) | (null); readonly "offset": number; readonly "run": ReviewRun; readonly "supplementary"?: (SignalSet) | (null); readonly "total": number; };
}
export type FindingList = FindingListSchema.FindingList;

// FindingPage.schema.json · SHA256 4cc3c52f4a453ac96bbde725f51a848d8f006e7a8d7b1c27f489787cec93d4d8
export namespace FindingPageSchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
  export type ChallengeCheck = { readonly "exhibit_tag"?: (string) | (null); readonly "found": boolean; readonly "item": string; readonly "searched": string; };
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type EvidenceStrength = "complete" | "partial" | "thin";
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type Finding = { readonly "checks"?: ReadonlyArray<ChallengeCheck>; readonly "conclusion": Conclusion; readonly "cwe": ReadonlyArray<number>; readonly "display_id": string; readonly "disposition"?: Disposition; readonly "disposition_reason"?: (string) | (null); readonly "exhibits": ReadonlyArray<Exhibit>; readonly "family": Family; readonly "flow"?: ReadonlyArray<FlowStep>; readonly "gaps"?: ReadonlyArray<string>; readonly "id": string; readonly "lede": string; readonly "peer_group_id"?: (string) | (null); readonly "policy_basis"?: ReadonlyArray<BoundPolicy>; readonly "probe_run_ids"?: ReadonlyArray<string>; readonly "question_ids"?: ReadonlyArray<string>; readonly "run_id": string; readonly "runtime_verification"?: RuntimeVerification; readonly "severity": Severity; readonly "severity_rationale": string; readonly "snapshot_id": string; readonly "strength": EvidenceStrength; readonly "suggested_change_id"?: (string) | (null); readonly "title": string; readonly "unknowns"?: ReadonlyArray<string>; };
  export type FlowStep = { readonly "exhibit_tag": string; readonly "label": string; };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type SecuritySignal = { readonly "advisory_id"?: (string) | (null); readonly "category": "secret" | "configuration" | "dependency"; readonly "ecosystem"?: ("npm" | "PyPI") | (null); readonly "fingerprint"?: (string) | (null); readonly "id": string; readonly "limitations": ReadonlyArray<string>; readonly "package"?: (string) | (null); readonly "rule_id": string; readonly "rule_version": string; readonly "source": SourceSpan; readonly "status": "observed" | "unknown"; readonly "summary": string; readonly "version"?: (string) | (null); };
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SignalSet = { readonly "limitations"?: ReadonlyArray<string>; readonly "pack_date"?: (string) | (null); readonly "pack_sha256"?: (string) | (null); readonly "pack_source"?: (string) | (null); readonly "run_id": string; readonly "signals"?: ReadonlyArray<SecuritySignal>; readonly "snapshot_id": string; readonly "status": "ok" | "partial" | "not_run"; readonly "tool_version": string; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type FindingPage = { readonly "findings": ReadonlyArray<Finding>; readonly "limitations": ReadonlyArray<string>; readonly "next_offset"?: (number) | (null); readonly "offset": number; readonly "run": ReviewRun; readonly "supplementary"?: (SignalSet) | (null); readonly "total": number; };
}
export type FindingPage = FindingPageSchema.FindingPage;

// FixProposal.schema.json · SHA256 027b5717d4f1d565cf15f83a63c7c3ff6fe9975ae6b1d258d3db4ba144f516d3
export namespace FixProposalSchema {
  export type Access = "allowed" | "denied";
  export type ChangeStatus = "proposed" | "replayed_fixed" | "replayed_not_fixed" | "replay_failed";
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type JsonValue = unknown;
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
  export type SourceEdit = { readonly "action": "replace" | "insert_before" | "insert_after" | "delete"; readonly "code": string; readonly "file_sha256": string; readonly "source": SourceSpan; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type StepRole = "setup" | "attack" | "control";
  export type SuggestedChange = { readonly "diff": string; readonly "files": ReadonlyArray<string>; readonly "finding_id": string; readonly "id": string; readonly "intent": string; readonly "replay_probe_run_ids"?: ReadonlyArray<string>; readonly "snapshot_id"?: (string) | (null); readonly "source_edits"?: ReadonlyArray<SourceEdit>; readonly "source_scope"?: (SourceSpan) | (null); readonly "status"?: ChangeStatus; };
  export type FixProposal = { readonly "adapter_manifest_sha256"?: (string) | (null); readonly "change"?: (SuggestedChange) | (null); readonly "finding_id": string; readonly "id": string; readonly "probe_reason": string; readonly "probe_spec"?: (ProbeSpec) | (null); readonly "probe_status"?: "available" | "unavailable"; readonly "reason": string; readonly "snapshot_id": string; readonly "status": "proposed" | "refused" | "unavailable"; };
}
export type FixProposal = FixProposalSchema.FixProposal;

// FixtureCreate.schema.json · SHA256 ef19882fe90367a3c870189f6c250b63a527fdd6c95e43ed2331e2cb6cb49359
export namespace FixtureCreateSchema {
  export type FixtureCreate = { readonly "variant"?: "open" | "defended"; };
}
export type FixtureCreate = FixtureCreateSchema.FixtureCreate;

// Guard.schema.json · SHA256 3391d129aca6de73ef5f8f9a7aa76dcb61c601bff9167d00221f5feba46e55cb
export namespace GuardSchema {
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type GuardMechanism = "dependency" | "decorator" | "query_filter" | "comparison" | "helper_call" | "data_access_layer" | "router" | "proxy_matcher";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Guard = { readonly "canonical": string; readonly "confirmed"?: boolean; readonly "id": string; readonly "kind": GuardKind; readonly "mechanism": GuardMechanism; readonly "object"?: (string) | (null); readonly "role"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; readonly "subject"?: (string) | (null); readonly "via_symbol_id"?: (string) | (null); };
}
export type Guard = GuardSchema.Guard;

// HTTPActionProgress.schema.json · SHA256 2d2e9ad6871b8c68e1416a1e3220dbf5af8a08956941c76cc9ff8fbb402d28c9
export namespace HTTPActionProgressSchema {
  export type HTTPActionProgress = { readonly "action_id": string; readonly "artifact_ids"?: ReadonlyArray<string>; readonly "attempts"?: number; readonly "completed"?: boolean; readonly "missing_evidence"?: ReadonlyArray<string>; };
}
export type HTTPActionProgress = HTTPActionProgressSchema.HTTPActionProgress;

// HumanAuthInput.schema.json · SHA256 57941c810e240c36dd56b67cf3f43da8fe01cab93fdc76382910b0ed227c8c31
export namespace HumanAuthInputSchema {
  export type HumanAuthInput = { readonly "kind": "pointer" | "text" | "submit" | "completed" | "pause" | "refresh"; readonly "text"?: (string) | (null); readonly "view_id": string; readonly "x"?: (number) | (null); readonly "y"?: (number) | (null); };
}
export type HumanAuthInput = HumanAuthInputSchema.HumanAuthInput;

// HumanAuthView.schema.json · SHA256 26895369afb5a962dcd4df060bc4fb43ba8e1415a69b2b9d6dee0564c3cda581
export namespace HumanAuthViewSchema {
  export type HumanAuthView = { readonly "account_id": string; readonly "challenge": "captcha" | "one_time_code" | "single_sign_on"; readonly "height"?: number; readonly "label": string; readonly "question": string; readonly "ready"?: true; readonly "screenshot_png": string; readonly "step_id": string; readonly "view_id": string; readonly "width"?: number; };
}
export type HumanAuthView = HumanAuthViewSchema.HumanAuthView;

// InspectRequest.schema.json · SHA256 eea4cf008c837fdf62a13f4e9da9ec0f5d6b7d0579b7be2618d432098f67a341
export namespace InspectRequestSchema {
  export type InspectRequest = { readonly "authorized": true; readonly "folder": string; };
}
export type InspectRequest = InspectRequestSchema.InspectRequest;

// InspectionView.schema.json · SHA256 e24f923fd64c16384c721fbab50df7286e52214edf3b94616ee1983a346a409d
export namespace InspectionViewSchema {
  export type CapabilityEvidence = { readonly "current_engine_acceptance"?: false; readonly "record": string; readonly "scope": string; readonly "sha256": string; };
  export type CapabilityRow = { readonly "category": "language" | "framework" | "family"; readonly "indexed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "indexed_units"?: (number) | (null); readonly "investigated"?: false; readonly "name": string; readonly "parsed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "parsed_units"?: (number) | (null); readonly "reason": string; readonly "runtime_testable"?: false; readonly "units"?: (number) | (null); readonly "workflow_implemented": boolean; };
  export type CapabilityTable = { readonly "evidence": ReadonlyArray<CapabilityEvidence>; readonly "quality_note": string; readonly "registry_sha256": string; readonly "rows": ReadonlyArray<CapabilityRow>; readonly "runtime_note": string; readonly "schema_version"?: 1; readonly "snapshot_id"?: (string) | (null); };
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type EntryPoint = { readonly "framework": Framework; readonly "handler_symbol_id": string; readonly "id": string; readonly "kind": EntryPointKind; readonly "method"?: (string) | (null); readonly "route"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type EntryPointKind = "http_route" | "route_handler" | "server_action" | "page";
  export type Framework = "fastapi" | "nextjs";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type InspectionView = { readonly "capabilities"?: (CapabilityTable) | (null); readonly "captured_at": string; readonly "conditions": ReadonlyArray<Condition>; readonly "entries": ReadonlyArray<EntryPoint>; readonly "entries_total": number; readonly "excluded_files": number; readonly "exclusion_reasons": Readonly<Record<string, number>>; readonly "frameworks": Readonly<Record<string, number>>; readonly "included_files": number; readonly "inspection_id"?: (string) | (null); readonly "languages": Readonly<Record<string, number>>; readonly "limitations": ReadonlyArray<string>; readonly "model_loaded"?: false; readonly "name": string; readonly "resources": Readonly<Record<string, number>>; readonly "snapshot_id": string; readonly "target_executed"?: false; readonly "unresolved_links": number; };
}
export type InspectionView = InspectionViewSchema.InspectionView;

// JourneyApprove.schema.json · SHA256 87b27530588d9de8356c4f6b9abc43f8581bdc7917c519feb007a932809ba7bb
export namespace JourneyApproveSchema {
  export type JourneyApprove = { readonly "approved_by": string; readonly "plan_sha256": string; readonly "reviewed_plan": true; readonly "step_ids"?: (ReadonlyArray<string>) | (null); };
}
export type JourneyApprove = JourneyApproveSchema.JourneyApprove;

// JourneyCreate.schema.json · SHA256 583bbb58729c335b761854f1365877597711e2f4b6af411005898459b3f991b9
export namespace JourneyCreateSchema {
  export type LoginConfig = { readonly "path": string; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type OwnerRule = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "object_id": string; readonly "rule_id": string; readonly "statement": string; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SignupConfig = { readonly "approved_side_effects": ReadonlyArray<string>; readonly "path": string; readonly "sends_messages": boolean; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type WebAccount = { readonly "account_id": string; readonly "contact_email"?: (string) | (null); readonly "contact_phone"?: (string) | (null); readonly "label": string; readonly "provisioned"?: boolean; readonly "role": string; readonly "secret_ref": string; readonly "username": string; };
  export type WebBudget = { readonly "max_bytes"?: number; readonly "max_model_questions"?: number; readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type WebObject = { readonly "kind": string; readonly "marker"?: (string) | (null); readonly "object_id": string; readonly "owner_account_id": string; readonly "path": string; readonly "synthetic"?: true; };
  export type WebTarget = { readonly "origin": string; readonly "paths": ReadonlyArray<string>; };
  export type WebsiteScope = { readonly "accounts"?: ReadonlyArray<WebAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report">; readonly "authority": ScopeAuthority; readonly "budget"?: WebBudget; readonly "confirmed_targets": true; readonly "expires_at": string; readonly "login"?: (LoginConfig) | (null); readonly "mode": "owned_fixture" | "external"; readonly "name": string; readonly "objects"?: ReadonlyArray<WebObject>; readonly "public_values"?: ReadonlyArray<string>; readonly "purpose": string; readonly "rules"?: ReadonlyArray<OwnerRule>; readonly "scope_id": string; readonly "signup"?: (SignupConfig) | (null); readonly "start_path"?: string; readonly "stop_conditions": ReadonlyArray<string>; readonly "targets": ReadonlyArray<WebTarget>; readonly "website_id": string; };
  export type JourneyCreate = { readonly "confirmed_authority": true; readonly "scope": WebsiteScope; };
}
export type JourneyCreate = JourneyCreateSchema.JourneyCreate;

// JourneyList.schema.json · SHA256 0e285ea33f90d9088ef8e38eed00003e85d6d87489ffb279c9189e1829c497ed
export namespace JourneyListSchema {
  export type AccountRecord = { readonly "account_id": string; readonly "note"?: string; readonly "session_kept"?: boolean; readonly "state"?: "not_tried" | "signed_in" | "created" | "failed" | "handoff" | "uncertain" | "needs_sign_in"; };
  export type BlockedRequest = { readonly "count"?: number; readonly "host": string; readonly "kind": "off_scope" | "redirect" | "websocket" | "download" | "budget" | "address" | "other"; readonly "reason": string; };
  export type CheckRecord = { readonly "check_id": string; readonly "citations"?: ReadonlyArray<EvidenceRef>; readonly "comparison"?: "candidate" | "protected" | "inconclusive" | "not_run"; readonly "facts"?: Readonly<Record<string, string>>; readonly "gaps"?: ReadonlyArray<string>; readonly "judged"?: ("supported" | "not_confirmed") | (null); readonly "judgment"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "note"?: string; readonly "object_id": string; readonly "other_account_id": string; readonly "owner_account_id": string; readonly "path": string; readonly "rule_id": string; readonly "state"?: "pending" | "completed" | "blocked"; };
  export type DecisionRecord = { readonly "at": string; readonly "attempts"?: ReadonlyArray<Readonly<Record<string, JsonValue>>>; readonly "question_type": string; readonly "reason"?: (string) | (null); readonly "rung": "code" | "model" | "model_reordered" | "user" | "stop"; readonly "stage": "scope" | "discover" | "authenticate" | "map" | "select" | "execute" | "challenge" | "record" | "report"; readonly "subject": string; readonly "value"?: (string) | (null); };
  export type EvidenceRef = { readonly "evidence_id": string; readonly "field": string; readonly "sha256": string; };
  export type Finding = { readonly "affected_application": string; readonly "affected_endpoint": string; readonly "check_id": string; readonly "conclusion": "supported" | "candidate"; readonly "description": string; readonly "evidence": ReadonlyArray<EvidenceRef>; readonly "explanation": string; readonly "explanation_source": "model" | "code"; readonly "finding_id": string; readonly "limits": ReadonlyArray<string>; readonly "methodology": ReadonlyArray<string>; readonly "mitigation": string; readonly "potential_impact": string; readonly "runtime"?: "observed_once_by_plumb_runner"; readonly "safe_reproduction": ReadonlyArray<string>; readonly "title": string; readonly "tools_and_models": ReadonlyArray<string>; };
  export type Incident = { readonly "at": string; readonly "content_kept"?: false; readonly "kinds": ReadonlyArray<string>; readonly "path": string; readonly "step_id": string; };
  export type JourneyView = { readonly "accounts"?: ReadonlyArray<AccountRecord>; readonly "activity"?: string; readonly "approval"?: (PlanApproval) | (null); readonly "approval_revoked_at"?: (string) | (null); readonly "approval_used_at"?: (string) | (null); readonly "blocked"?: ReadonlyArray<BlockedRequest>; readonly "browser"?: "not_used" | "used" | "unavailable"; readonly "browser_note"?: string; readonly "checks"?: ReadonlyArray<CheckRecord>; readonly "confidentiality"?: "private_local"; readonly "created_at": string; readonly "decisions"?: ReadonlyArray<DecisionRecord>; readonly "evidence"?: ReadonlyArray<WebEvidence>; readonly "findings"?: ReadonlyArray<Finding>; readonly "handoffs"?: ReadonlyArray<string>; readonly "incidents"?: ReadonlyArray<Incident>; readonly "journey_id": string; readonly "leads"?: ReadonlyArray<string>; readonly "pages"?: ReadonlyArray<PageRecord>; readonly "plan": WebsitePlan; readonly "plan_sha256": string; readonly "report_path"?: (string) | (null); readonly "scope": WebsiteScope; readonly "spent"?: Spent; readonly "stage"?: "scope" | "discover" | "authenticate" | "map" | "select" | "execute" | "challenge" | "record" | "report"; readonly "status"?: "planned" | "approved" | "running" | "paused" | "stopped" | "handoff" | "done" | "failed"; readonly "steps"?: ReadonlyArray<StepRecord>; readonly "stop_reason"?: (string) | (null); readonly "updated_at": string; readonly "waiting"?: ReadonlyArray<UserQuestion>; };
  export type JsonValue = unknown;
  export type LoginConfig = { readonly "path": string; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type OwnerRule = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "object_id": string; readonly "rule_id": string; readonly "statement": string; };
  export type PageRecord = { readonly "account_id"?: (string) | (null); readonly "blocked"?: ReadonlyArray<BlockedRequest>; readonly "evidence_id"?: (string) | (null); readonly "forms"?: ReadonlyArray<string>; readonly "kind"?: string; readonly "kind_rung"?: ("code" | "model" | "model_reordered" | "user" | "stop") | (null); readonly "links"?: number; readonly "note"?: string; readonly "path": string; readonly "status"?: (number) | (null); readonly "title"?: string; readonly "via": "http" | "browser"; };
  export type PlanApproval = { readonly "approved_by": string; readonly "approved_step_ids": ReadonlyArray<string>; readonly "expires_at": string; readonly "granted_at": string; readonly "plan_sha256": string; readonly "reviewed_plan": true; };
  export type PlanStep = { readonly "account_id"?: (string) | (null); readonly "action": "read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report"; readonly "max_requests": number; readonly "object_id"?: (string) | (null); readonly "stage": "discover" | "authenticate" | "map" | "check" | "report"; readonly "state_changing": boolean; readonly "step_id": string; readonly "summary": string; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SignupConfig = { readonly "approved_side_effects": ReadonlyArray<string>; readonly "path": string; readonly "sends_messages": boolean; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type Spent = { readonly "bytes"?: number; readonly "model_questions"?: number; readonly "model_seconds"?: number; readonly "requests"?: number; readonly "seconds"?: number; };
  export type StepRecord = { readonly "action": "read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report"; readonly "evidence_ids"?: ReadonlyArray<string>; readonly "note"?: string; readonly "requests"?: number; readonly "state"?: "planned" | "attempted" | "completed" | "uncertain" | "blocked" | "skipped"; readonly "step_id": string; };
  export type UserChoice = { readonly "label": string; readonly "meaning": string; };
  export type UserQuestion = { readonly "choices": ReadonlyArray<UserChoice>; readonly "question_type": string; readonly "subject": string; readonly "text": string; };
  export type WebAccount = { readonly "account_id": string; readonly "contact_email"?: (string) | (null); readonly "contact_phone"?: (string) | (null); readonly "label": string; readonly "provisioned"?: boolean; readonly "role": string; readonly "secret_ref": string; readonly "username": string; };
  export type WebBudget = { readonly "max_bytes"?: number; readonly "max_model_questions"?: number; readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type WebEvidence = { readonly "account_id"?: (string) | (null); readonly "collected_at": string; readonly "evidence_id": string; readonly "fields": Readonly<Record<string, string>>; readonly "kind": "page" | "response" | "comparison" | "screenshot" | "note"; readonly "object_id"?: (string) | (null); readonly "provenance": string; readonly "reviewed"?: boolean; readonly "sha256": string; readonly "via": "http" | "browser" | "code"; readonly "website_id": string; };
  export type WebObject = { readonly "kind": string; readonly "marker"?: (string) | (null); readonly "object_id": string; readonly "owner_account_id": string; readonly "path": string; readonly "synthetic"?: true; };
  export type WebTarget = { readonly "origin": string; readonly "paths": ReadonlyArray<string>; };
  export type WebsitePlan = { readonly "budget": WebBudget; readonly "created_at": string; readonly "expected_model_seconds": number; readonly "expires_at": string; readonly "model_questions": number; readonly "not_covered"?: ReadonlyArray<string>; readonly "plan_id": string; readonly "scope_sha256": string; readonly "steps": ReadonlyArray<PlanStep>; readonly "unmeasured_question_types"?: ReadonlyArray<string>; readonly "website_id": string; };
  export type WebsiteScope = { readonly "accounts"?: ReadonlyArray<WebAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report">; readonly "authority": ScopeAuthority; readonly "budget"?: WebBudget; readonly "confirmed_targets": true; readonly "expires_at": string; readonly "login"?: (LoginConfig) | (null); readonly "mode": "owned_fixture" | "external"; readonly "name": string; readonly "objects"?: ReadonlyArray<WebObject>; readonly "public_values"?: ReadonlyArray<string>; readonly "purpose": string; readonly "rules"?: ReadonlyArray<OwnerRule>; readonly "scope_id": string; readonly "signup"?: (SignupConfig) | (null); readonly "start_path"?: string; readonly "stop_conditions": ReadonlyArray<string>; readonly "targets": ReadonlyArray<WebTarget>; readonly "website_id": string; };
  export type JourneyList = { readonly "journeys": ReadonlyArray<JourneyView>; };
}
export type JourneyList = JourneyListSchema.JourneyList;

// JourneyRun.schema.json · SHA256 478390fefb1866c75fce9b04965cc52ab099dbb5bd88d2e591a49570899734e9
export namespace JourneyRunSchema {
  export type JourneyRun = { readonly "answers"?: Readonly<Record<string, string>>; readonly "profile"?: string; readonly "secrets"?: Readonly<Record<string, string>>; readonly "use_model"?: boolean; };
}
export type JourneyRun = JourneyRunSchema.JourneyRun;

// JourneyView.schema.json · SHA256 1a8fe8bc55040974d1f870dfc8d614d763bb65763dc772f1dfb604f2e1af4897
export namespace JourneyViewSchema {
  export type AccountRecord = { readonly "account_id": string; readonly "note"?: string; readonly "session_kept"?: boolean; readonly "state"?: "not_tried" | "signed_in" | "created" | "failed" | "handoff" | "uncertain" | "needs_sign_in"; };
  export type BlockedRequest = { readonly "count"?: number; readonly "host": string; readonly "kind": "off_scope" | "redirect" | "websocket" | "download" | "budget" | "address" | "other"; readonly "reason": string; };
  export type CheckRecord = { readonly "check_id": string; readonly "citations"?: ReadonlyArray<EvidenceRef>; readonly "comparison"?: "candidate" | "protected" | "inconclusive" | "not_run"; readonly "facts"?: Readonly<Record<string, string>>; readonly "gaps"?: ReadonlyArray<string>; readonly "judged"?: ("supported" | "not_confirmed") | (null); readonly "judgment"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "note"?: string; readonly "object_id": string; readonly "other_account_id": string; readonly "owner_account_id": string; readonly "path": string; readonly "rule_id": string; readonly "state"?: "pending" | "completed" | "blocked"; };
  export type DecisionRecord = { readonly "at": string; readonly "attempts"?: ReadonlyArray<Readonly<Record<string, JsonValue>>>; readonly "question_type": string; readonly "reason"?: (string) | (null); readonly "rung": "code" | "model" | "model_reordered" | "user" | "stop"; readonly "stage": "scope" | "discover" | "authenticate" | "map" | "select" | "execute" | "challenge" | "record" | "report"; readonly "subject": string; readonly "value"?: (string) | (null); };
  export type EvidenceRef = { readonly "evidence_id": string; readonly "field": string; readonly "sha256": string; };
  export type Finding = { readonly "affected_application": string; readonly "affected_endpoint": string; readonly "check_id": string; readonly "conclusion": "supported" | "candidate"; readonly "description": string; readonly "evidence": ReadonlyArray<EvidenceRef>; readonly "explanation": string; readonly "explanation_source": "model" | "code"; readonly "finding_id": string; readonly "limits": ReadonlyArray<string>; readonly "methodology": ReadonlyArray<string>; readonly "mitigation": string; readonly "potential_impact": string; readonly "runtime"?: "observed_once_by_plumb_runner"; readonly "safe_reproduction": ReadonlyArray<string>; readonly "title": string; readonly "tools_and_models": ReadonlyArray<string>; };
  export type Incident = { readonly "at": string; readonly "content_kept"?: false; readonly "kinds": ReadonlyArray<string>; readonly "path": string; readonly "step_id": string; };
  export type JsonValue = unknown;
  export type LoginConfig = { readonly "path": string; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type OwnerRule = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "object_id": string; readonly "rule_id": string; readonly "statement": string; };
  export type PageRecord = { readonly "account_id"?: (string) | (null); readonly "blocked"?: ReadonlyArray<BlockedRequest>; readonly "evidence_id"?: (string) | (null); readonly "forms"?: ReadonlyArray<string>; readonly "kind"?: string; readonly "kind_rung"?: ("code" | "model" | "model_reordered" | "user" | "stop") | (null); readonly "links"?: number; readonly "note"?: string; readonly "path": string; readonly "status"?: (number) | (null); readonly "title"?: string; readonly "via": "http" | "browser"; };
  export type PlanApproval = { readonly "approved_by": string; readonly "approved_step_ids": ReadonlyArray<string>; readonly "expires_at": string; readonly "granted_at": string; readonly "plan_sha256": string; readonly "reviewed_plan": true; };
  export type PlanStep = { readonly "account_id"?: (string) | (null); readonly "action": "read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report"; readonly "max_requests": number; readonly "object_id"?: (string) | (null); readonly "stage": "discover" | "authenticate" | "map" | "check" | "report"; readonly "state_changing": boolean; readonly "step_id": string; readonly "summary": string; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SignupConfig = { readonly "approved_side_effects": ReadonlyArray<string>; readonly "path": string; readonly "sends_messages": boolean; readonly "success_path"?: (string) | (null); readonly "success_text"?: (string) | (null); };
  export type Spent = { readonly "bytes"?: number; readonly "model_questions"?: number; readonly "model_seconds"?: number; readonly "requests"?: number; readonly "seconds"?: number; };
  export type StepRecord = { readonly "action": "read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report"; readonly "evidence_ids"?: ReadonlyArray<string>; readonly "note"?: string; readonly "requests"?: number; readonly "state"?: "planned" | "attempted" | "completed" | "uncertain" | "blocked" | "skipped"; readonly "step_id": string; };
  export type UserChoice = { readonly "label": string; readonly "meaning": string; };
  export type UserQuestion = { readonly "choices": ReadonlyArray<UserChoice>; readonly "question_type": string; readonly "subject": string; readonly "text": string; };
  export type WebAccount = { readonly "account_id": string; readonly "contact_email"?: (string) | (null); readonly "contact_phone"?: (string) | (null); readonly "label": string; readonly "provisioned"?: boolean; readonly "role": string; readonly "secret_ref": string; readonly "username": string; };
  export type WebBudget = { readonly "max_bytes"?: number; readonly "max_model_questions"?: number; readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type WebEvidence = { readonly "account_id"?: (string) | (null); readonly "collected_at": string; readonly "evidence_id": string; readonly "fields": Readonly<Record<string, string>>; readonly "kind": "page" | "response" | "comparison" | "screenshot" | "note"; readonly "object_id"?: (string) | (null); readonly "provenance": string; readonly "reviewed"?: boolean; readonly "sha256": string; readonly "via": "http" | "browser" | "code"; readonly "website_id": string; };
  export type WebObject = { readonly "kind": string; readonly "marker"?: (string) | (null); readonly "object_id": string; readonly "owner_account_id": string; readonly "path": string; readonly "synthetic"?: true; };
  export type WebTarget = { readonly "origin": string; readonly "paths": ReadonlyArray<string>; };
  export type WebsitePlan = { readonly "budget": WebBudget; readonly "created_at": string; readonly "expected_model_seconds": number; readonly "expires_at": string; readonly "model_questions": number; readonly "not_covered"?: ReadonlyArray<string>; readonly "plan_id": string; readonly "scope_sha256": string; readonly "steps": ReadonlyArray<PlanStep>; readonly "unmeasured_question_types"?: ReadonlyArray<string>; readonly "website_id": string; };
  export type WebsiteScope = { readonly "accounts"?: ReadonlyArray<WebAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "sign_in" | "sign_up" | "submit_form" | "compare" | "report">; readonly "authority": ScopeAuthority; readonly "budget"?: WebBudget; readonly "confirmed_targets": true; readonly "expires_at": string; readonly "login"?: (LoginConfig) | (null); readonly "mode": "owned_fixture" | "external"; readonly "name": string; readonly "objects"?: ReadonlyArray<WebObject>; readonly "public_values"?: ReadonlyArray<string>; readonly "purpose": string; readonly "rules"?: ReadonlyArray<OwnerRule>; readonly "scope_id": string; readonly "signup"?: (SignupConfig) | (null); readonly "start_path"?: string; readonly "stop_conditions": ReadonlyArray<string>; readonly "targets": ReadonlyArray<WebTarget>; readonly "website_id": string; };
  export type JourneyView = { readonly "accounts"?: ReadonlyArray<AccountRecord>; readonly "activity"?: string; readonly "approval"?: (PlanApproval) | (null); readonly "approval_revoked_at"?: (string) | (null); readonly "approval_used_at"?: (string) | (null); readonly "blocked"?: ReadonlyArray<BlockedRequest>; readonly "browser"?: "not_used" | "used" | "unavailable"; readonly "browser_note"?: string; readonly "checks"?: ReadonlyArray<CheckRecord>; readonly "confidentiality"?: "private_local"; readonly "created_at": string; readonly "decisions"?: ReadonlyArray<DecisionRecord>; readonly "evidence"?: ReadonlyArray<WebEvidence>; readonly "findings"?: ReadonlyArray<Finding>; readonly "handoffs"?: ReadonlyArray<string>; readonly "incidents"?: ReadonlyArray<Incident>; readonly "journey_id": string; readonly "leads"?: ReadonlyArray<string>; readonly "pages"?: ReadonlyArray<PageRecord>; readonly "plan": WebsitePlan; readonly "plan_sha256": string; readonly "report_path"?: (string) | (null); readonly "scope": WebsiteScope; readonly "spent"?: Spent; readonly "stage"?: "scope" | "discover" | "authenticate" | "map" | "select" | "execute" | "challenge" | "record" | "report"; readonly "status"?: "planned" | "approved" | "running" | "paused" | "stopped" | "handoff" | "done" | "failed"; readonly "steps"?: ReadonlyArray<StepRecord>; readonly "stop_reason"?: (string) | (null); readonly "updated_at": string; readonly "waiting"?: ReadonlyArray<UserQuestion>; };
}
export type JourneyView = JourneyViewSchema.JourneyView;

// LabActionPreview.schema.json · SHA256 625c7215955854db6e3b4b36bab1c3a753e7f549b32fc898d70725123dca73ab
export namespace LabActionPreviewSchema {
  export type Access = "allowed" | "denied";
  export type ControlledHTTPAction = { readonly "account_id": ("alice" | "bob") | (null); readonly "action_id": string; readonly "body_preview"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "max_attempts"?: number; readonly "method": "GET" | "POST"; readonly "path": string; readonly "purpose": "readiness" | "authenticate" | "create_synthetic" | "read"; readonly "state_change": boolean; };
  export type ControlledHTTPPreview = { readonly "actions": ReadonlyArray<ControlledHTTPAction>; readonly "assessment_id": string; readonly "control_spec"?: (ProbeSpec) | (null); readonly "created_at": string; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "max_requests": number; readonly "max_response_bytes"?: number; readonly "max_seconds": number; readonly "max_total_bytes"?: number; readonly "preview_id": string; readonly "runner"?: "hash_pinned_owned_tandir"; readonly "runner_manifest_sha256": string; readonly "scope_sha256": string; readonly "spec": ProbeSpec; readonly "synthetic_object_id": string; };
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type JsonValue = unknown;
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
  export type StepRole = "setup" | "attack" | "control";
  export type LabActionPreview = { readonly "preview": ControlledHTTPPreview; readonly "preview_sha256": string; };
}
export type LabActionPreview = LabActionPreviewSchema.LabActionPreview;

// LabActionPreviewRequest.schema.json · SHA256 6323c5d618897aabae68a690f7f27d543a95e376e9e8c84883632b6b410e3852
export namespace LabActionPreviewRequestSchema {
  export type LabActionPreviewRequest = { readonly "invoice"?: boolean; readonly "paired"?: boolean; };
}
export type LabActionPreviewRequest = LabActionPreviewRequestSchema.LabActionPreviewRequest;

// LabActionRunRequest.schema.json · SHA256 11906cefa2fd3092972c922eaabd72e9f5899560a31d20e2899897d2806fadf2
export namespace LabActionRunRequestSchema {
  export type ControlledHTTPPermission = { readonly "approved_action_ids": ReadonlyArray<string>; readonly "approved_by": string; readonly "expires_at": string; readonly "granted_at": string; readonly "preview_sha256": string; readonly "reviewed_preview": true; };
  export type LabActionRunRequest = { readonly "permission": ControlledHTTPPermission; readonly "preview_sha256": string; };
}
export type LabActionRunRequest = LabActionRunRequestSchema.LabActionRunRequest;

// LabCollectionCheckpoint.schema.json · SHA256 d7545a0a80025528cb161c449787ce8ed849dc355808608507a900680eafe0a2
export namespace LabCollectionCheckpointSchema {
  export type Access = "allowed" | "denied";
  export type ControlledHTTPAction = { readonly "account_id": ("alice" | "bob") | (null); readonly "action_id": string; readonly "body_preview"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "max_attempts"?: number; readonly "method": "GET" | "POST"; readonly "path": string; readonly "purpose": "readiness" | "authenticate" | "create_synthetic" | "read"; readonly "state_change": boolean; };
  export type ControlledHTTPPermission = { readonly "approved_action_ids": ReadonlyArray<string>; readonly "approved_by": string; readonly "expires_at": string; readonly "granted_at": string; readonly "preview_sha256": string; readonly "reviewed_preview": true; };
  export type ControlledHTTPPreview = { readonly "actions": ReadonlyArray<ControlledHTTPAction>; readonly "assessment_id": string; readonly "control_spec"?: (ProbeSpec) | (null); readonly "created_at": string; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "max_requests": number; readonly "max_response_bytes"?: number; readonly "max_seconds": number; readonly "max_total_bytes"?: number; readonly "preview_id": string; readonly "runner"?: "hash_pinned_owned_tandir"; readonly "runner_manifest_sha256": string; readonly "scope_sha256": string; readonly "spec": ProbeSpec; readonly "synthetic_object_id": string; };
  export type ControlledHTTPResult = { readonly "action_progress"?: ReadonlyArray<HTTPActionProgress>; readonly "bytes_received"?: number; readonly "execution_status"?: "collected_owned_lab"; readonly "preview_id": string; readonly "preview_sha256": string; readonly "records"?: ReadonlyArray<Readonly<Record<string, JsonValue>>>; readonly "requests_used": number; readonly "runner_manifest_sha256": string; readonly "runner_origin"?: (string) | (null); readonly "runtime_verification"?: "not_attempted"; readonly "seconds": number; readonly "stop_reason"?: (string) | (null); readonly "stopped": boolean; };
  export type HTTPActionProgress = { readonly "action_id": string; readonly "artifact_ids"?: ReadonlyArray<string>; readonly "attempts"?: number; readonly "completed"?: boolean; readonly "missing_evidence"?: ReadonlyArray<string>; };
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type JsonValue = unknown;
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
  export type StepRole = "setup" | "attack" | "control";
  export type LabCollectionCheckpoint = { readonly "assessment_id": string; readonly "automatic_replay_allowed"?: false; readonly "evidence_review_required"?: true; readonly "message": string; readonly "permission"?: (ControlledHTTPPermission) | (null); readonly "phase": "proposed" | "approved" | "executing" | "completed" | "stopped" | "interrupted"; readonly "preview": ControlledHTTPPreview; readonly "preview_sha256": string; readonly "result"?: (ControlledHTTPResult) | (null); readonly "updated_at": string; };
}
export type LabCollectionCheckpoint = LabCollectionCheckpointSchema.LabCollectionCheckpoint;

// LabCollectionImportRequest.schema.json · SHA256 c84cff3dd325eb4878c82988c0c58e1c4e39d82c6c0e4d192aaa2a17343826f2
export namespace LabCollectionImportRequestSchema {
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type LabCollectionImportRequest = { readonly "prepare_website_comparisons"?: boolean; readonly "preview_sha256": string; readonly "review": AttachmentReview; };
}
export type LabCollectionImportRequest = LabCollectionImportRequestSchema.LabCollectionImportRequest;

// LaunchRequest.schema.json · SHA256 8d13758dd6cd4c2552d044d5ff2a950c069cb3d7e448fc16375423ff6337ce9d
export namespace LaunchRequestSchema {
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type LaunchRequest = { readonly "authorized": true; readonly "families"?: ReadonlyArray<Family>; readonly "inspection_id": string; readonly "limit"?: number; readonly "profile"?: string; readonly "prompt_task_id"?: (string) | (null); readonly "resources"?: ReadonlyArray<string>; readonly "routes"?: ReadonlyArray<string>; };
}
export type LaunchRequest = LaunchRequestSchema.LaunchRequest;

// ModelCatalog.schema.json · SHA256 4af1064e6957172c6b1c703c9fca559022f7e6c92aa46fb1698bc1bc2f4c0d41
export namespace ModelCatalogSchema {
  export type ModelChoice = { readonly "family": string; readonly "model_id": string; readonly "profiles": ReadonlyArray<ModelProfileChoice>; readonly "quantization": string; readonly "requires_download_approval": boolean; readonly "size_bytes": number; readonly "unavailable_reason"?: (string) | (null); readonly "verified_installed": boolean; };
  export type ModelProfileChoice = { readonly "automatic_eligible": boolean; readonly "available_vram_bytes": (number) | (null); readonly "backend": "cpu" | "vulkan"; readonly "conditions": ReadonlyArray<string>; readonly "first_use_check": "not needed" | "pending" | "passed" | "failed"; readonly "hardware_compatible": boolean; readonly "launch_available": boolean; readonly "memory_fit": boolean; readonly "profile_id": string; readonly "quality_note": string; readonly "quality_records": ReadonlyArray<ModelQualityRecord>; readonly "quality_state": "recorded_scoped" | "untested"; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "runtime_compatible": (boolean) | (null); readonly "runtime_verified": boolean; };
  export type ModelQualityRecord = { readonly "path": string; readonly "sha256": string; };
  export type ModelCatalog = { readonly "available_ram_bytes": number; readonly "available_vram_bytes": (number) | (null); readonly "checked_at": string; readonly "downloads_started"?: false; readonly "model_loaded"?: false; readonly "models": ReadonlyArray<ModelChoice>; readonly "recommended_profile": (string) | (null); readonly "selected_profile": (string) | (null); readonly "selection_basis": string; };
}
export type ModelCatalog = ModelCatalogSchema.ModelCatalog;

// ModelChoice.schema.json · SHA256 c222b3e4afd0558dfb09e2f723b8b4d8f08c756b29a8e88f9edeffc23d79146f
export namespace ModelChoiceSchema {
  export type ModelProfileChoice = { readonly "automatic_eligible": boolean; readonly "available_vram_bytes": (number) | (null); readonly "backend": "cpu" | "vulkan"; readonly "conditions": ReadonlyArray<string>; readonly "first_use_check": "not needed" | "pending" | "passed" | "failed"; readonly "hardware_compatible": boolean; readonly "launch_available": boolean; readonly "memory_fit": boolean; readonly "profile_id": string; readonly "quality_note": string; readonly "quality_records": ReadonlyArray<ModelQualityRecord>; readonly "quality_state": "recorded_scoped" | "untested"; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "runtime_compatible": (boolean) | (null); readonly "runtime_verified": boolean; };
  export type ModelQualityRecord = { readonly "path": string; readonly "sha256": string; };
  export type ModelChoice = { readonly "family": string; readonly "model_id": string; readonly "profiles": ReadonlyArray<ModelProfileChoice>; readonly "quantization": string; readonly "requires_download_approval": boolean; readonly "size_bytes": number; readonly "unavailable_reason"?: (string) | (null); readonly "verified_installed": boolean; };
}
export type ModelChoice = ModelChoiceSchema.ModelChoice;

// ModelProfileChoice.schema.json · SHA256 55b4112da3d6de68eb974c2d14b74929781553e44861135b75571ebfbab156b2
export namespace ModelProfileChoiceSchema {
  export type ModelQualityRecord = { readonly "path": string; readonly "sha256": string; };
  export type ModelProfileChoice = { readonly "automatic_eligible": boolean; readonly "available_vram_bytes": (number) | (null); readonly "backend": "cpu" | "vulkan"; readonly "conditions": ReadonlyArray<string>; readonly "first_use_check": "not needed" | "pending" | "passed" | "failed"; readonly "hardware_compatible": boolean; readonly "launch_available": boolean; readonly "memory_fit": boolean; readonly "profile_id": string; readonly "quality_note": string; readonly "quality_records": ReadonlyArray<ModelQualityRecord>; readonly "quality_state": "recorded_scoped" | "untested"; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "runtime_compatible": (boolean) | (null); readonly "runtime_verified": boolean; };
}
export type ModelProfileChoice = ModelProfileChoiceSchema.ModelProfileChoice;

// ObservationAnalysis.schema.json · SHA256 9d1e81cf5ebcf317aa8e0b13b80d2fee5301101db9c441a50c16e14fadca74aa
export namespace ObservationAnalysisSchema {
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type ObservationClaim = { readonly "citation": EvidenceCitation; readonly "value": string; };
  export type ObservationJudgment = { readonly "alternative_explanations": ReadonlyArray<string>; readonly "claims": ReadonlyArray<ObservationClaim>; readonly "missing_evidence": ReadonlyArray<string>; readonly "mitigation": string; readonly "rationale": string; readonly "verdict": "supported" | "rejected" | "inconclusive"; };
  export type ValidatedObservationJudgment = { readonly "answer"?: (ObservationJudgment) | (null); readonly "error"?: (string) | (null); readonly "evidence_order": ReadonlyArray<string>; readonly "raw_answer"?: (string) | (null); readonly "seed": number; readonly "violations"?: ReadonlyArray<string>; };
  export type ObservationAnalysis = { readonly "alternative_explanations": ReadonlyArray<string>; readonly "citations": ReadonlyArray<EvidenceCitation>; readonly "comparison_id": string; readonly "conclusion": "supported" | "rejected" | "inconclusive"; readonly "generated_by"?: "local_model"; readonly "judgments": ReadonlyArray<ValidatedObservationJudgment>; readonly "missing_evidence": ReadonlyArray<string>; readonly "model_provenance"?: ReadonlyArray<string>; readonly "packet_sha256": string; readonly "requests_used": number; readonly "runtime_verification"?: "not_attempted"; readonly "seconds": number; readonly "stop_reason"?: (string) | (null); };
}
export type ObservationAnalysis = ObservationAnalysisSchema.ObservationAnalysis;

// ObservationAnalysisRequest.schema.json · SHA256 d513863e1d8c45c8925de7bcde6a1eecf97dcf805f0a344bad7936093fa88f16
export namespace ObservationAnalysisRequestSchema {
  export type ObservationAnalysisRequest = { readonly "approach"?: "baseline" | "facts" | "decomposed"; readonly "comparison_id": string; readonly "guidance_card_id"?: (string) | (null); readonly "profile"?: string; };
}
export type ObservationAnalysisRequest = ObservationAnalysisRequestSchema.ObservationAnalysisRequest;

// ObservationComparison.schema.json · SHA256 67780992318e8ee2d7ac8431ddd3ffe44c30299da66c0b1541df50dea7d3d5d4
export namespace ObservationComparisonSchema {
  export type ComparisonRequest = { readonly "control_artifact_id"?: (string) | (null); readonly "expectation_id"?: (string) | (null); readonly "left_artifact_id": string; readonly "right_artifact_id": string; };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type ObservationComparison = { readonly "alternative_explanations"?: ReadonlyArray<string>; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "comparison_id": string; readonly "conclusion": "candidate" | "rejected" | "inconclusive"; readonly "execution_status"?: "imported"; readonly "missing_evidence"?: ReadonlyArray<string>; readonly "request": ComparisonRequest; readonly "summary": string; };
}
export type ObservationComparison = ObservationComparisonSchema.ObservationComparison;

// ObservationJudgment.schema.json · SHA256 eac3709e6349005119c0535254edab198114f7373bcea1f6b2783248a4c709ce
export namespace ObservationJudgmentSchema {
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type ObservationClaim = { readonly "citation": EvidenceCitation; readonly "value": string; };
  export type ObservationJudgment = { readonly "alternative_explanations": ReadonlyArray<string>; readonly "claims": ReadonlyArray<ObservationClaim>; readonly "missing_evidence": ReadonlyArray<string>; readonly "mitigation": string; readonly "rationale": string; readonly "verdict": "supported" | "rejected" | "inconclusive"; };
}
export type ObservationJudgment = ObservationJudgmentSchema.ObservationJudgment;

// ObservedMap.schema.json · SHA256 a453b9ce1eae6b152f0c4f29424e90475ff089468a857151021bd44c1a185542
export namespace ObservedMapSchema {
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type ObservedEndpoint = { readonly "account_ids": ReadonlyArray<string>; readonly "artifact_ids": ReadonlyArray<string>; readonly "citations": ReadonlyArray<EvidenceCitation>; readonly "coverage"?: "observed_import"; readonly "endpoint_id": string; readonly "method": string; readonly "object_ids": ReadonlyArray<string>; readonly "path": string; };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type ObservedMap = { readonly "assessment_id": string; readonly "collection_performed"?: false; readonly "declared_roles": ReadonlyArray<TestAccount>; readonly "endpoints"?: ReadonlyArray<ObservedEndpoint>; readonly "unknowns": ReadonlyArray<string>; };
}
export type ObservedMap = ObservedMapSchema.ObservedMap;

// PeerExcerpt.schema.json · SHA256 c678332397f13ba378336bf765929c897efbaaf9a4da5833e3d9a8c0fee73b65
export namespace PeerExcerptSchema {
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type PeerExcerpt = { readonly "citation": number; readonly "comments_are_not_evidence"?: true; readonly "end_line": number; readonly "finding_id": string; readonly "lines": ReadonlyArray<string>; readonly "next_offset"?: (number) | (null); readonly "run_id": string; readonly "site_id": string; readonly "span": SourceSpan; readonly "start_line": number; readonly "text_is_redacted"?: true; };
}
export type PeerExcerpt = PeerExcerptSchema.PeerExcerpt;

// PeerGroup.schema.json · SHA256 254de1e3ee78fd3122fb055060a0f1803f15297c8dd64632a38c5420d228f5de
export namespace PeerGroupSchema {
  export type PeerColumn = { readonly "applied_site_ids": ReadonlyArray<string>; readonly "key": string; readonly "label": string; };
  export type PeerDeviation = { readonly "missing": string; readonly "peers_applying": number; readonly "peers_total": number; readonly "site_id": string; };
  export type PeerExclusion = { readonly "reason": string; readonly "site_id": string; };
  export type PeerGroup = { readonly "columns": ReadonlyArray<PeerColumn>; readonly "deviations"?: ReadonlyArray<PeerDeviation>; readonly "excluded"?: ReadonlyArray<PeerExclusion>; readonly "id": string; readonly "min_peers"?: number; readonly "min_share"?: number; readonly "resource": string; readonly "site_ids": ReadonlyArray<string>; readonly "snapshot_id": string; };
}
export type PeerGroup = PeerGroupSchema.PeerGroup;

// PolicyAssertion.schema.json · SHA256 14e7268f010db8fad741761e0777b6584d113dfea4fd3ebfd9fe158ca06446fa
export namespace PolicyAssertionSchema {
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
}
export type PolicyAssertion = PolicyAssertionSchema.PolicyAssertion;

// PolicyConfirm.schema.json · SHA256 8c3708cf58df2fe72e6df6113287116d4ce4ffda4c648913ef9be55423d35204
export namespace PolicyConfirmSchema {
  export type PolicyConfirm = { readonly "proposal_sha256": string; };
}
export type PolicyConfirm = PolicyConfirmSchema.PolicyConfirm;

// PolicyInput.schema.json · SHA256 1e5ca8d15beb849c2ac8c679143445ea653b4448e5aa44e0761333188d46d16d
export namespace PolicyInputSchema {
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type PolicyInput = { readonly "author": string; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "required_guard"?: (GuardKind) | (null); readonly "required_role"?: (string) | (null); readonly "site_ids": ReadonlyArray<string>; readonly "snapshot_id": string; readonly "statement": string; };
}
export type PolicyInput = PolicyInputSchema.PolicyInput;

// PrivateReportRequest.schema.json · SHA256 3c8c1c9d0426789604e43caff9105e94486e613b53d98429b324ad43e55fdc3a
export namespace PrivateReportRequestSchema {
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type PrivateReportRequest = { readonly "preview_sha256": string; readonly "review": AttachmentReview; };
}
export type PrivateReportRequest = PrivateReportRequestSchema.PrivateReportRequest;

// ProbeRun.schema.json · SHA256 17d2e8092510729c586332ad86da4d61ef6c6cab107577ac130ec2302c14b8b8
export namespace ProbeRunSchema {
  export type Access = "allowed" | "denied";
  export type ProbeOutcome = "reproduced" | "not_reproduced" | "fixed" | "not_fixed" | "inconclusive";
  export type ProbeStep = { readonly "error"?: (string) | (null); readonly "expected_if_safe": Access; readonly "marker_present"?: (boolean) | (null); readonly "method": string; readonly "path": string; readonly "principal": string; readonly "role": StepRole; readonly "status"?: (number) | (null); };
  export type RunnerKind = "bundled_lab" | "windows_sandbox" | "docker";
  export type SnapshotRole = "vulnerable" | "patched";
  export type StepRole = "setup" | "attack" | "control";
  export type ProbeRun = { readonly "finding_id": string; readonly "finished_at": string; readonly "id": string; readonly "outcome": ProbeOutcome; readonly "runner": RunnerKind; readonly "runner_manifest_sha256": string; readonly "snapshot_id": string; readonly "snapshot_role": SnapshotRole; readonly "started_at": string; readonly "steps": ReadonlyArray<ProbeStep>; };
}
export type ProbeRun = ProbeRunSchema.ProbeRun;

// ProbeSpec.schema.json · SHA256 cd3af19b968e77103370999cadac722e280b0a60a08f501910f8913d7289b450
export namespace ProbeSpecSchema {
  export type Access = "allowed" | "denied";
  export type HTTPProbeRequest = { readonly "body"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "capture"?: Readonly<Record<string, string>>; readonly "expected_if_safe": Access; readonly "method": "GET" | "POST"; readonly "path": string; readonly "principal": string; readonly "role": StepRole; };
  export type JsonValue = unknown;
  export type StepRole = "setup" | "attack" | "control";
  export type ProbeSpec = { readonly "finding_id": string; readonly "id": string; readonly "marker": string; readonly "requests": ReadonlyArray<HTTPProbeRequest>; };
}
export type ProbeSpec = ProbeSpecSchema.ProbeSpec;

// ProjectExcerpt.schema.json · SHA256 5e46d73677066e41db26281d3de3c4a05600c494812e3693eb019f9e0f7f6c9b
export namespace ProjectExcerptSchema {
  export type ProjectCitation = { readonly "id": string; readonly "span": SourceSpan; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type ProjectExcerpt = { readonly "citation": ProjectCitation; readonly "end_line": number; readonly "lines": ReadonlyArray<string>; readonly "next_offset": (number) | (null); readonly "offset": number; readonly "run_id": string; readonly "start_line": number; };
}
export type ProjectExcerpt = ProjectExcerptSchema.ProjectExcerpt;

// ProjectPage.schema.json · SHA256 e9ea7e7859f92e3ab8b21630e1042fc7ed714df295c609688e1969e21aca90c3
export namespace ProjectPageSchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
  export type CapabilityEvidence = { readonly "current_engine_acceptance"?: false; readonly "record": string; readonly "scope": string; readonly "sha256": string; };
  export type CapabilityRow = { readonly "category": "language" | "framework" | "family"; readonly "indexed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "indexed_units"?: (number) | (null); readonly "investigated"?: false; readonly "name": string; readonly "parsed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "parsed_units"?: (number) | (null); readonly "reason": string; readonly "runtime_testable"?: false; readonly "units"?: (number) | (null); readonly "workflow_implemented": boolean; };
  export type CapabilityTable = { readonly "evidence": ReadonlyArray<CapabilityEvidence>; readonly "quality_note": string; readonly "registry_sha256": string; readonly "rows": ReadonlyArray<CapabilityRow>; readonly "runtime_note": string; readonly "schema_version"?: 1; readonly "snapshot_id"?: (string) | (null); };
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type ExcludedFile = { readonly "path": string; readonly "reason": ExclusionReason; };
  export type ExclusionReason = "too_large" | "binary" | "link" | "unsupported" | "secret" | "user_excluded" | "unreadable" | "sealed" | "default_ignored";
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type LinkStatus = "resolved" | "inferred" | "unresolved";
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type ProjectCitation = { readonly "id": string; readonly "span": SourceSpan; };
  export type ProjectEdge = { readonly "id": string; readonly "kind": string; readonly "optimistic": boolean; readonly "reason": string; readonly "source": string; readonly "status": LinkStatus; readonly "target": string; };
  export type ProjectFlow = { readonly "data": ReadonlyArray<ProjectNode>; readonly "data_total": number; readonly "entry": ProjectNode; readonly "guards": ReadonlyArray<ProjectNode>; readonly "guards_total": number; readonly "links": ReadonlyArray<ProjectEdge>; readonly "optimistic_links": number; readonly "unresolved_links": number; };
  export type ProjectNode = { readonly "citation": ProjectCitation; readonly "detail": string; readonly "id": string; readonly "label": string; readonly "optimistic"?: boolean; };
  export type ProjectRule = { readonly "assertion": PolicyAssertion; readonly "citations": ReadonlyArray<ProjectCitation>; readonly "guard_forms": ReadonlyArray<string>; readonly "proposal_sha256": string; readonly "sites_applying": number; readonly "sites_total": number; readonly "source_run_id": string; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type ProjectPage = { readonly "bound_policies"?: ReadonlyArray<BoundPolicy>; readonly "capabilities"?: (CapabilityTable) | (null); readonly "captured_at": string; readonly "excluded_files": number; readonly "exclusion_reasons": Readonly<Record<string, number>>; readonly "exclusions": ReadonlyArray<ExcludedFile>; readonly "flows": ReadonlyArray<ProjectFlow>; readonly "flows_total": number; readonly "frameworks": Readonly<Record<string, number>>; readonly "included_files": number; readonly "languages": Readonly<Record<string, number>>; readonly "limitations": ReadonlyArray<string>; readonly "name": string; readonly "next_offset": (number) | (null); readonly "offset": number; readonly "optimistic_links": number; readonly "policy_conflicts"?: ReadonlyArray<string>; readonly "policy_next_offset": (number) | (null); readonly "policy_offset": number; readonly "resources": Readonly<Record<string, number>>; readonly "rules": ReadonlyArray<ProjectRule>; readonly "rules_total": number; readonly "run_id": string; readonly "scope_next_offset": (number) | (null); readonly "scope_offset": number; readonly "snapshot_id": string; readonly "unresolved_links": number; };
}
export type ProjectPage = ProjectPageSchema.ProjectPage;

// ProjectRule.schema.json · SHA256 8d6cb768fde7cf239b1fca4b098e18b181708fa6bad11ba19bb978ecb2780fec
export namespace ProjectRuleSchema {
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type ProjectCitation = { readonly "id": string; readonly "span": SourceSpan; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type ProjectRule = { readonly "assertion": PolicyAssertion; readonly "citations": ReadonlyArray<ProjectCitation>; readonly "guard_forms": ReadonlyArray<string>; readonly "proposal_sha256": string; readonly "sites_applying": number; readonly "sites_total": number; readonly "source_run_id": string; };
}
export type ProjectRule = ProjectRuleSchema.ProjectRule;

// ProjectSnapshot.schema.json · SHA256 8c084228ebc54a3e580615190520a05387ddffbc34c1175708c095b70a89cd0a
export namespace ProjectSnapshotSchema {
  export type ExcludedFile = { readonly "path": string; readonly "reason": ExclusionReason; };
  export type ExclusionReason = "too_large" | "binary" | "link" | "unsupported" | "secret" | "user_excluded" | "unreadable" | "sealed" | "default_ignored";
  export type Language = "python" | "typescript" | "tsx" | "javascript";
  export type SnapshotFile = { readonly "language"?: (Language) | (null); readonly "path": string; readonly "sha256": string; readonly "size": number; };
  export type ProjectSnapshot = { readonly "created_at": string; readonly "dirty"?: (boolean) | (null); readonly "excluded"?: ReadonlyArray<ExcludedFile>; readonly "files": ReadonlyArray<SnapshotFile>; readonly "git_commit"?: (string) | (null); readonly "id": string; readonly "root_name": string; };
}
export type ProjectSnapshot = ProjectSnapshotSchema.ProjectSnapshot;

// Question.schema.json · SHA256 81f9468e3a115b80ed95f68f34592e734c5b90d4b65790774ec32a77079ad97d
export namespace QuestionSchema {
  export type Budget = { readonly "max_looks"?: number; readonly "max_prompt_tokens"?: number; readonly "max_retries"?: number; readonly "max_seconds"?: number; };
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type JsonValue = unknown;
  export type QuestionStage = "frame" | "gather" | "hypothesize" | "challenge" | "decide" | "verify" | "record";
  export type QuestionStatus = "pending" | "excluded" | "running" | "answered" | "rejected_by_validator" | "inconclusive" | "budget_exhausted" | "canceled" | "failed";
  export type QuestionType = "guard_summary" | "guard_equivalent" | "input_origin" | "sink_safety" | "intentional_exception" | "client_exposure" | "fix_sketch";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Question = { readonly "answer"?: (Readonly<Record<string, JsonValue>>) | (null); readonly "budget"?: Budget; readonly "evidence": ReadonlyArray<SourceSpan>; readonly "exploration"?: boolean; readonly "family": Family; readonly "id": string; readonly "observation_ids"?: ReadonlyArray<string>; readonly "priority_reasons"?: ReadonlyArray<string>; readonly "run_id": string; readonly "stage": QuestionStage; readonly "status": QuestionStatus; readonly "subject_ids": ReadonlyArray<string>; readonly "type": QuestionType; };
}
export type Question = QuestionSchema.Question;

// QueueEdit.schema.json · SHA256 aedee4ac2bf40d47d2bd6f7d11eab9dc95f397cabb4f1f1956e27386c883eee5
export namespace QueueEditSchema {
  export type QueueEdit = { readonly "action": "up" | "down" | "exclude" | "include"; readonly "expected_cursor": number; readonly "offset"?: number; readonly "question_id": string; };
}
export type QueueEdit = QueueEditSchema.QueueEdit;

// ReportPreview.schema.json · SHA256 693ce2737a373cf60150b0847bb32a5cb0efe6c78db553fcca3b3d484829a16e
export namespace ReportPreviewSchema {
  export type AccessExpectation = { readonly "allowed_account_ids": ReadonlyArray<string>; readonly "basis": string; readonly "declared_by": string; readonly "expectation_id": string; readonly "object_id": string; readonly "path": string; readonly "statement": string; };
  export type AssessmentReport = { readonly "affected_endpoints": ReadonlyArray<string>; readonly "assessment_id": string; readonly "claims": ReadonlyArray<ReportClaim>; readonly "comparisons": ReadonlyArray<ObservationComparison>; readonly "confidentiality"?: "private_local"; readonly "description": string; readonly "dismissed_leads": ReadonlyArray<string>; readonly "evidence": ReadonlyArray<EvidenceArtifact>; readonly "expected_behavior": ReadonlyArray<AccessExpectation>; readonly "human_preview_required"?: true; readonly "impact": string; readonly "limitations": ReadonlyArray<string>; readonly "methodology": ReadonlyArray<string>; readonly "mitigation": ReadonlyArray<string>; readonly "runtime_verification"?: "not_attempted"; readonly "safe_reproduction": ReadonlyArray<string>; readonly "tested_coverage": ReadonlyArray<string>; readonly "title": string; readonly "tools_and_models": ReadonlyArray<string>; readonly "untested_coverage": ReadonlyArray<string>; };
  export type AttachmentReview = { readonly "confirmed_sanitized": true; readonly "reviewed_at": string; readonly "reviewed_by": string; };
  export type ComparisonRequest = { readonly "control_artifact_id"?: (string) | (null); readonly "expectation_id"?: (string) | (null); readonly "left_artifact_id": string; readonly "right_artifact_id": string; };
  export type EvidenceArtifact = { readonly "artifact_id": string; readonly "assessment_id": string; readonly "attachment_path"?: (string) | (null); readonly "collected_at": string; readonly "context"?: (ObservationContext) | (null); readonly "execution_status"?: "imported"; readonly "fields": Readonly<Record<string, string>>; readonly "imported_at": string; readonly "kind": "request_response" | "note" | "screenshot"; readonly "provenance": string; readonly "review": AttachmentReview; readonly "sha256": string; readonly "trusted_lab_collection"?: (LabCollectionBinding) | (null); };
  export type EvidenceCitation = { readonly "artifact_id": string; readonly "field": string; readonly "sha256": string; };
  export type LabCollectionBinding = { readonly "manifest_sha256": string; readonly "preview_sha256": string; readonly "runner_origin": string; readonly "scope_origin": string; };
  export type ObservationComparison = { readonly "alternative_explanations"?: ReadonlyArray<string>; readonly "citations"?: ReadonlyArray<EvidenceCitation>; readonly "comparison_id": string; readonly "conclusion": "candidate" | "rejected" | "inconclusive"; readonly "execution_status"?: "imported"; readonly "missing_evidence"?: ReadonlyArray<string>; readonly "request": ComparisonRequest; readonly "summary": string; };
  export type ObservationContext = { readonly "account_id": string; readonly "object_id": string; readonly "request_context_id": string; readonly "session_context_id": string; };
  export type ReportClaim = { readonly "citations": ReadonlyArray<EvidenceCitation>; readonly "text": string; };
  export type ReportPreview = { readonly "export_path"?: (string) | (null); readonly "markdown": string; readonly "preview_sha256": string; readonly "report": AssessmentReport; readonly "submitted"?: false; };
}
export type ReportPreview = ReportPreviewSchema.ReportPreview;

// ResumeRequest.schema.json · SHA256 e788f3d3f44c9d09305eed13651796e4c30c46293992ca52204676ba1ac5c60f
export namespace ResumeRequestSchema {
  export type ResumeRequest = { readonly "limit"?: number; };
}
export type ResumeRequest = ResumeRequestSchema.ResumeRequest;

// ReviewPage.schema.json · SHA256 79d15648a2de6bbbd7324f5031456bc89846151372449c603d560d7f17657d4f
export namespace ReviewPageSchema {
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type EventKind = "run.started" | "run.resumed" | "run.paused" | "run.canceled" | "run.failed" | "run.completed" | "run.queue_changed" | "question.started" | "question.stage" | "question.activity" | "question.finished";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type QuestionStage = "frame" | "gather" | "hypothesize" | "challenge" | "decide" | "verify" | "record";
  export type QuestionStatus = "pending" | "excluded" | "running" | "answered" | "rejected_by_validator" | "inconclusive" | "budget_exhausted" | "canceled" | "failed";
  export type QuestionType = "guard_summary" | "guard_equivalent" | "input_origin" | "sink_safety" | "intentional_exception" | "client_exposure" | "fix_sketch";
  export type QueueRow = { readonly "exploration": boolean; readonly "family": Family; readonly "id": string; readonly "location": (SourceSpan) | (null); readonly "original_position"?: (number) | (null); readonly "position": number; readonly "priority_reasons": ReadonlyArray<string>; readonly "stage": QuestionStage; readonly "status": QuestionStatus; readonly "type": QuestionType; };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunEvent = { readonly "at": string; readonly "coverage"?: (Coverage) | (null); readonly "kind": EventKind; readonly "message"?: (string) | (null); readonly "question_id"?: (string) | (null); readonly "run_id": string; readonly "seq": number; readonly "stage"?: (QuestionStage) | (null); readonly "status"?: (QuestionStatus) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type ReviewPage = { readonly "cursor": number; readonly "events": ReadonlyArray<RunEvent>; readonly "next_offset": (number) | (null); readonly "offset": number; readonly "questions": ReadonlyArray<QueueRow>; readonly "queue_excluded"?: number; readonly "requested": ("pause" | "cancel") | (null); readonly "run": ReviewRun; readonly "total": number; };
}
export type ReviewPage = ReviewPageSchema.ReviewPage;

// ReviewRun.schema.json · SHA256 7b7d72db4880e2084b47ea39e38827e7ab902c8467b81dc68c229fb1383b3153
export namespace ReviewRunSchema {
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
}
export type ReviewRun = ReviewRunSchema.ReviewRun;

// RunComparison.schema.json · SHA256 70485a2404835a2c7679282cfedb3ca871cce15b35c3e886926d3404d5d0e8e6
export namespace RunComparisonSchema {
  export type ComparisonRow = { readonly "after": (FindingRow) | (null); readonly "before": (FindingRow) | (null); readonly "group": "new" | "still_present" | "no_longer_observed" | "not_reviewed"; readonly "id": string; readonly "reason": string; };
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type FindingRow = { readonly "conclusion": Conclusion; readonly "display_id": string; readonly "disposition": Disposition; readonly "family": Family; readonly "id": string; readonly "location": (SourceSpan) | (null); readonly "runtime_verification": RuntimeVerification; readonly "severity": Severity; readonly "title": string; };
  export type GuardCount = { readonly "applying": number; readonly "citations": ReadonlyArray<ProjectCitation>; readonly "total": number; };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type PolicyDrift = { readonly "after": (GuardCount) | (null); readonly "before": (GuardCount) | (null); readonly "cohort_changed": boolean; readonly "kind": GuardKind; readonly "reason": string; readonly "resource": string; };
  export type ProjectCitation = { readonly "id": string; readonly "span": SourceSpan; };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type RunComparison = { readonly "after": ReviewRun; readonly "before": ReviewRun; readonly "counts": Readonly<Record<string, number>>; readonly "group": "new" | "still_present" | "no_longer_observed" | "not_reviewed"; readonly "limitations": ReadonlyArray<string>; readonly "next_offset": (number) | (null); readonly "offset": number; readonly "policies": ReadonlyArray<PolicyDrift>; readonly "policies_total": number; readonly "policy_next_offset": (number) | (null); readonly "policy_offset": number; readonly "rows": ReadonlyArray<ComparisonRow>; };
}
export type RunComparison = RunComparisonSchema.RunComparison;

// RunEvent.schema.json · SHA256 ce3c953641e582e6df97c02aac5e76148bf14cc365abbad00e523f5d84fc21fe
export namespace RunEventSchema {
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type EventKind = "run.started" | "run.resumed" | "run.paused" | "run.canceled" | "run.failed" | "run.completed" | "run.queue_changed" | "question.started" | "question.stage" | "question.activity" | "question.finished";
  export type QuestionStage = "frame" | "gather" | "hypothesize" | "challenge" | "decide" | "verify" | "record";
  export type QuestionStatus = "pending" | "excluded" | "running" | "answered" | "rejected_by_validator" | "inconclusive" | "budget_exhausted" | "canceled" | "failed";
  export type RunEvent = { readonly "at": string; readonly "coverage"?: (Coverage) | (null); readonly "kind": EventKind; readonly "message"?: (string) | (null); readonly "question_id"?: (string) | (null); readonly "run_id": string; readonly "seq": number; readonly "stage"?: (QuestionStage) | (null); readonly "status"?: (QuestionStatus) | (null); };
}
export type RunEvent = RunEventSchema.RunEvent;

// RunHistory.schema.json · SHA256 77fd00193afda2502ea98cd41287d47f71bd9d43aca0e963f8347f572c60c065
export namespace RunHistorySchema {
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type Coverage = { readonly "completed"?: number; readonly "excluded"?: number; readonly "pending"?: number; readonly "total"?: number; readonly "unsupported"?: number; };
  export type ModelRef = { readonly "file_sha256": string; readonly "id": string; readonly "quantization": string; };
  export type ReviewRun = { readonly "conditions"?: ReadonlyArray<Condition>; readonly "coverage"?: Coverage; readonly "created_at": string; readonly "finding_ids"?: ReadonlyArray<string>; readonly "finished_at"?: (string) | (null); readonly "id": string; readonly "lifecycle": RunLifecycle; readonly "model"?: (ModelRef) | (null); readonly "run_type": RunType; readonly "snapshot_id": string; readonly "stage"?: (RunStage) | (null); readonly "started_at"?: (string) | (null); readonly "toolchain"?: (Toolchain) | (null); };
  export type RunLifecycle = "queued" | "running" | "paused" | "canceled" | "failed" | "completed";
  export type RunStage = "indexing" | "scanning" | "investigating" | "verifying" | "reporting";
  export type RunType = "live" | "replay" | "saved";
  export type Toolchain = { readonly "backend": string; readonly "knowledge_pack_date"?: (string) | (null); readonly "llama_cpp_build": string; readonly "llama_cpp_release": string; readonly "opengrep_rules_sha256"?: (string) | (null); readonly "opengrep_version"?: (string) | (null); };
  export type RunHistory = { readonly "next_offset": (number) | (null); readonly "offset": number; readonly "runs": ReadonlyArray<ReviewRun>; readonly "total": number; };
}
export type RunHistory = RunHistorySchema.RunHistory;

// SavedAnswerRequest.schema.json · SHA256 277ffb7dbe7efdf4fa63655b31a8a7ccb06d252e0dffc35211d05fcfdf948001
export namespace SavedAnswerRequestSchema {
  export type SavedAnswerRequest = { readonly "prompt": string; };
}
export type SavedAnswerRequest = SavedAnswerRequestSchema.SavedAnswerRequest;

// SavedFindingAnswer.schema.json · SHA256 1f18530401f4b23ddba146059dfa24832c26a6b97ce951dbdda979435fa7d062
export namespace SavedFindingAnswerSchema {
  export type AccessSite = { readonly "data_layer": DataLayer; readonly "entry_point_id": string; readonly "guard_ids"?: ReadonlyArray<string>; readonly "id": string; readonly "key_origin": InputOrigin; readonly "operation": Operation; readonly "resource": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
  export type BoundPolicy = { readonly "assertion": PolicyAssertion; readonly "forbidden_fields"?: ReadonlyArray<string>; readonly "provenance": string; readonly "required_role"?: (string) | (null); readonly "sites": ReadonlyArray<AccessSite>; readonly "snapshot_id": string; readonly "source_run_id": string; };
  export type ChallengeCheck = { readonly "exhibit_tag"?: (string) | (null); readonly "found": boolean; readonly "item": string; readonly "searched": string; };
  export type Conclusion = "candidate" | "supported" | "rejected" | "inconclusive";
  export type DataLayer = "sqlalchemy" | "raw_sql" | "prisma" | "drizzle" | "other";
  export type Disposition = "open" | "dismissed" | "accepted_risk" | "resolved";
  export type EvidenceStrength = "complete" | "partial" | "thin";
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type Finding = { readonly "checks"?: ReadonlyArray<ChallengeCheck>; readonly "conclusion": Conclusion; readonly "cwe": ReadonlyArray<number>; readonly "display_id": string; readonly "disposition"?: Disposition; readonly "disposition_reason"?: (string) | (null); readonly "exhibits": ReadonlyArray<Exhibit>; readonly "family": Family; readonly "flow"?: ReadonlyArray<FlowStep>; readonly "gaps"?: ReadonlyArray<string>; readonly "id": string; readonly "lede": string; readonly "peer_group_id"?: (string) | (null); readonly "policy_basis"?: ReadonlyArray<BoundPolicy>; readonly "probe_run_ids"?: ReadonlyArray<string>; readonly "question_ids"?: ReadonlyArray<string>; readonly "run_id": string; readonly "runtime_verification"?: RuntimeVerification; readonly "severity": Severity; readonly "severity_rationale": string; readonly "snapshot_id": string; readonly "strength": EvidenceStrength; readonly "suggested_change_id"?: (string) | (null); readonly "title": string; readonly "unknowns"?: ReadonlyArray<string>; };
  export type FlowStep = { readonly "exhibit_tag": string; readonly "label": string; };
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type InputOrigin = "path" | "query" | "body" | "header" | "session" | "constant" | "unknown";
  export type Operation = "read" | "list" | "create" | "update" | "delete";
  export type PolicyAssertion = { readonly "author": string; readonly "canonical": string; readonly "confirmed_at"?: (string) | (null); readonly "confirmed_by"?: (string) | (null); readonly "created_at": string; readonly "evidence"?: ReadonlyArray<SourceSpan>; readonly "id": string; readonly "kind": GuardKind; readonly "resource": string; readonly "statement": string; readonly "status": PolicyStatus; };
  export type PolicyStatus = "inferred" | "confirmed" | "declared";
  export type RuntimeVerification = "not_attempted" | "unavailable" | "inconclusive" | "reproduced" | "not_reproduced";
  export type Severity = "critical" | "high" | "medium" | "low" | "unknown";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type SavedFindingAnswer = { readonly "authorization_granted"?: false; readonly "finding": Finding; readonly "generated_by"?: "saved_evidence"; readonly "limitations": ReadonlyArray<string>; readonly "network_activity"?: false; readonly "prompt": string; readonly "report_path": string; readonly "run_id": string; };
}
export type SavedFindingAnswer = SavedFindingAnswerSchema.SavedFindingAnswer;

// SavedResults.schema.json · SHA256 261aacb2a6d8eeb86b89c774159e9fddff64867a855c46486aad79f8aa6ce17d
export namespace SavedResultsSchema {
  export type SavedResult = { readonly "label": string; readonly "target_id": string; readonly "target_kind": "inspection" | "review" | "assessment" | "website"; };
  export type SavedResults = { readonly "results": ReadonlyArray<SavedResult>; };
}
export type SavedResults = SavedResultsSchema.SavedResults;

// ScopeCreate.schema.json · SHA256 81ec9619f0011283b48cbc10c973a6d3284ec1643a4962cae787bf1efcf91239
export namespace ScopeCreateSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentScope = { readonly "accounts": ReadonlyArray<TestAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "compare" | "plan" | "report" | "analyze" | "collect" | "authenticate" | "create_synthetic">; readonly "allowed_paths": ReadonlyArray<string>; readonly "application_id": string; readonly "application_name": string; readonly "assessment_id": string; readonly "authority": ScopeAuthority; readonly "budget"?: AssessmentBudget; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "origin": string; readonly "scope_id": string; readonly "stop_conditions": ReadonlyArray<string>; readonly "synthetic_objects"?: ReadonlyArray<SyntheticObject>; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SyntheticObject = { readonly "kind": string; readonly "object_id": string; readonly "owner_account_id": string; readonly "synthetic"?: true; readonly "synthetic_marker"?: (string) | (null); };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type ScopeCreate = { readonly "confirmed_authority": true; readonly "scope": AssessmentScope; };
}
export type ScopeCreate = ScopeCreateSchema.ScopeCreate;

// SetupReadiness.schema.json · SHA256 2f19028bbfb6394cd29f1b6070e038259eb17e5ad4fb2df7933542d53f3c0153
export namespace SetupReadinessSchema {
  export type CapabilityEvidence = { readonly "current_engine_acceptance"?: false; readonly "record": string; readonly "scope": string; readonly "sha256": string; };
  export type CapabilityRow = { readonly "category": "language" | "framework" | "family"; readonly "indexed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "indexed_units"?: (number) | (null); readonly "investigated"?: false; readonly "name": string; readonly "parsed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "parsed_units"?: (number) | (null); readonly "reason": string; readonly "runtime_testable"?: false; readonly "units"?: (number) | (null); readonly "workflow_implemented": boolean; };
  export type CapabilityTable = { readonly "evidence": ReadonlyArray<CapabilityEvidence>; readonly "quality_note": string; readonly "registry_sha256": string; readonly "rows": ReadonlyArray<CapabilityRow>; readonly "runtime_note": string; readonly "schema_version"?: 1; readonly "snapshot_id"?: (string) | (null); };
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type ModelCatalog = { readonly "available_ram_bytes": number; readonly "available_vram_bytes": (number) | (null); readonly "checked_at": string; readonly "downloads_started"?: false; readonly "model_loaded"?: false; readonly "models": ReadonlyArray<ModelChoice>; readonly "recommended_profile": (string) | (null); readonly "selected_profile": (string) | (null); readonly "selection_basis": string; };
  export type ModelChoice = { readonly "family": string; readonly "model_id": string; readonly "profiles": ReadonlyArray<ModelProfileChoice>; readonly "quantization": string; readonly "requires_download_approval": boolean; readonly "size_bytes": number; readonly "unavailable_reason"?: (string) | (null); readonly "verified_installed": boolean; };
  export type ModelProfileChoice = { readonly "automatic_eligible": boolean; readonly "available_vram_bytes": (number) | (null); readonly "backend": "cpu" | "vulkan"; readonly "conditions": ReadonlyArray<string>; readonly "first_use_check": "not needed" | "pending" | "passed" | "failed"; readonly "hardware_compatible": boolean; readonly "launch_available": boolean; readonly "memory_fit": boolean; readonly "profile_id": string; readonly "quality_note": string; readonly "quality_records": ReadonlyArray<ModelQualityRecord>; readonly "quality_state": "recorded_scoped" | "untested"; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "runtime_compatible": (boolean) | (null); readonly "runtime_verified": boolean; };
  export type ModelQualityRecord = { readonly "path": string; readonly "sha256": string; };
  export type SetupReadiness = { readonly "available_ram_bytes": number; readonly "available_vram_bytes": (number) | (null); readonly "capabilities"?: (CapabilityTable) | (null); readonly "checked_at": string; readonly "conditions": ReadonlyArray<Condition>; readonly "downloads_started"?: false; readonly "inspect_ready": boolean; readonly "limitations": ReadonlyArray<string>; readonly "measured_host": boolean; readonly "memory_fit": boolean; readonly "missing_download_bytes": number; readonly "model_catalog"?: (ModelCatalog) | (null); readonly "model_id": string; readonly "model_loaded"?: false; readonly "model_size_bytes": number; readonly "model_verified": boolean; readonly "profile_id": string; readonly "ready": boolean; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "requires_large_download_approval": boolean; readonly "runtime_verified": boolean; };
}
export type SetupReadiness = SetupReadinessSchema.SetupReadiness;

// SignalSet.schema.json · SHA256 f0b9f79516ff1fa7ea4c32ad6b1d1db6ea256c150b6c1b6f9473dc7e3673174f
export namespace SignalSetSchema {
  export type SecuritySignal = { readonly "advisory_id"?: (string) | (null); readonly "category": "secret" | "configuration" | "dependency"; readonly "ecosystem"?: ("npm" | "PyPI") | (null); readonly "fingerprint"?: (string) | (null); readonly "id": string; readonly "limitations": ReadonlyArray<string>; readonly "package"?: (string) | (null); readonly "rule_id": string; readonly "rule_version": string; readonly "source": SourceSpan; readonly "status": "observed" | "unknown"; readonly "summary": string; readonly "version"?: (string) | (null); };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type SignalSet = { readonly "limitations"?: ReadonlyArray<string>; readonly "pack_date"?: (string) | (null); readonly "pack_sha256"?: (string) | (null); readonly "pack_source"?: (string) | (null); readonly "run_id": string; readonly "signals"?: ReadonlyArray<SecuritySignal>; readonly "snapshot_id": string; readonly "status": "ok" | "partial" | "not_run"; readonly "tool_version": string; };
}
export type SignalSet = SignalSetSchema.SignalSet;

// SnapshotCodePage.schema.json · SHA256 3267815d3fb7a14a6051ddb3d130d8884a8f4402a805e4b64f7c7fdd22d5317f
export namespace SnapshotCodePageSchema {
  export type Language = "python" | "typescript" | "tsx" | "javascript";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type SnapshotCodePage = { readonly "after": number; readonly "before": number; readonly "citation": SourceSpan; readonly "comments_are_not_evidence"?: true; readonly "context_is_not_evidence"?: true; readonly "end_line": number; readonly "file_line_count": number; readonly "file_sha256": string; readonly "finding_id": string; readonly "language"?: (Language) | (null); readonly "lines": ReadonlyArray<string>; readonly "mode": "context" | "file"; readonly "next_offset"?: (number) | (null); readonly "offset": number; readonly "range_end": number; readonly "range_start": number; readonly "run_id": string; readonly "start_line": number; readonly "text_is_redacted"?: true; };
}
export type SnapshotCodePage = SnapshotCodePageSchema.SnapshotCodePage;

// SourceCheck.schema.json · SHA256 53e33c269e33c53dbc301f844f4d269807ee4a3349202459734c5ff4f395a908
export namespace SourceCheckSchema {
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type SourceCheck = { readonly "added_files"?: (number) | (null); readonly "changed_files"?: (number) | (null); readonly "checked_at": string; readonly "conditions"?: ReadonlyArray<Condition>; readonly "current_snapshot_id"?: (string) | (null); readonly "excluded_scope_changed"?: (boolean) | (null); readonly "limitations": ReadonlyArray<string>; readonly "model_loaded"?: false; readonly "removed_files"?: (number) | (null); readonly "run_id": string; readonly "snapshot_id": string; readonly "state": "current" | "changed" | "unavailable" | "unassociated"; readonly "target_executed"?: false; };
}
export type SourceCheck = SourceCheckSchema.SourceCheck;

// SourcePromptRequest.schema.json · SHA256 37c3cea84c8d81996503f80f40447842fa99dda1ebd735166af6093bb8165dd2
export namespace SourcePromptRequestSchema {
  export type SourcePromptRequest = { readonly "inspection_id": string; readonly "limit"?: number; readonly "prompt": string; };
}
export type SourcePromptRequest = SourcePromptRequestSchema.SourcePromptRequest;

// SourcePromptResolution.schema.json · SHA256 fb6c7ce7eb8e6dc24f78ff6b4676f2e2d2e59b18a9130ea72fb8d3c75835ebd2
export namespace SourcePromptResolutionSchema {
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type SourcePromptResolution = { readonly "authorization_granted"?: false; readonly "clarification"?: (string) | (null); readonly "families": ReadonlyArray<Family>; readonly "limit": number; readonly "network_activity"?: false; readonly "prompt": string; readonly "resources": ReadonlyArray<string>; readonly "routes": ReadonlyArray<string>; readonly "status": "resolved" | "clarification_required" | "refused"; readonly "target_id": string; readonly "task_id": string; };
}
export type SourcePromptResolution = SourcePromptResolutionSchema.SourcePromptResolution;

// SourceSpan.schema.json · SHA256 958d6cd5a368d3c0fb7b6c257ced6981196537b69e6722eeea24fcf7fc1d65ec
export namespace SourceSpanSchema {
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
}
export type SourceSpan = SourceSpanSchema.SourceSpan;

// SuggestedChange.schema.json · SHA256 509ab83889d95ce453a194445fc9b9539357df0a8fa35bee2a419264173082fb
export namespace SuggestedChangeSchema {
  export type ChangeStatus = "proposed" | "replayed_fixed" | "replayed_not_fixed" | "replay_failed";
  export type SourceEdit = { readonly "action": "replace" | "insert_before" | "insert_after" | "delete"; readonly "code": string; readonly "file_sha256": string; readonly "source": SourceSpan; };
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type SuggestedChange = { readonly "diff": string; readonly "files": ReadonlyArray<string>; readonly "finding_id": string; readonly "id": string; readonly "intent": string; readonly "replay_probe_run_ids"?: ReadonlyArray<string>; readonly "snapshot_id"?: (string) | (null); readonly "source_edits"?: ReadonlyArray<SourceEdit>; readonly "source_scope"?: (SourceSpan) | (null); readonly "status"?: ChangeStatus; };
}
export type SuggestedChange = SuggestedChangeSchema.SuggestedChange;

// Symbol.schema.json · SHA256 0dff032beb00e5ec038ef22ebe6d4bbcc6bb51170eb9db68e7b6e0fdc9955183
export namespace SymbolSchema {
  export type Language = "python" | "typescript" | "tsx" | "javascript";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type SymbolKind = "module" | "class" | "function" | "method" | "variable" | "component" | "type";
  export type Symbol = { readonly "id": string; readonly "kind": SymbolKind; readonly "language": Language; readonly "name": string; readonly "qualified_name": string; readonly "snapshot_id": string; readonly "span": SourceSpan; };
}
export type Symbol = SymbolSchema.Symbol;

// TaskResolveRequest.schema.json · SHA256 6bc3228c83a7a0e48365d9d83dd3801796b31cef1a354f91b0ee23b23dbb5625
export namespace TaskResolveRequestSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type TaskResolveRequest = { readonly "budget"?: AssessmentBudget; readonly "evidence_ids"?: ReadonlyArray<string>; readonly "prompt": string; };
}
export type TaskResolveRequest = TaskResolveRequestSchema.TaskResolveRequest;

// ToolObservation.schema.json · SHA256 03d982822f06ea293f979b2c11fbaae30342ec39028bda400acfad23dc80734d
export namespace ToolObservationSchema {
  export type JsonValue = unknown;
  export type ObservationStatus = "ok" | "error" | "timeout" | "refused";
  export type ToolObservation = { readonly "finished_at": string; readonly "id": string; readonly "inputs": Readonly<Record<string, JsonValue>>; readonly "output_sha256"?: (string) | (null); readonly "question_id"?: (string) | (null); readonly "run_id": string; readonly "started_at": string; readonly "status": ObservationStatus; readonly "tool": string; readonly "tool_version": string; };
}
export type ToolObservation = ToolObservationSchema.ToolObservation;

// WebsiteReadiness.schema.json · SHA256 007a7282b79dfbc0741cbe40b3b92974986b3aa06e0aa6ad34c3bc4d79963454
export namespace WebsiteReadinessSchema {
  export type WebsiteReadiness = { readonly "browser_note": string; readonly "browser_ready": boolean; readonly "external_note": string; readonly "external_ready": boolean; };
}
export type WebsiteReadiness = WebsiteReadinessSchema.WebsiteReadiness;

// WebsiteScopeCreate.schema.json · SHA256 b8f39971a475caa807a3045ba91a30f4be59eae19c8013180b21a727ab151cfd
export namespace WebsiteScopeCreateSchema {
  export type AssessmentBudget = { readonly "max_requests"?: number; readonly "max_seconds"?: number; };
  export type AssessmentScope = { readonly "accounts": ReadonlyArray<TestAccount>; readonly "allowed_actions": ReadonlyArray<"read" | "compare" | "plan" | "report" | "analyze" | "collect" | "authenticate" | "create_synthetic">; readonly "allowed_paths": ReadonlyArray<string>; readonly "application_id": string; readonly "application_name": string; readonly "assessment_id": string; readonly "authority": ScopeAuthority; readonly "budget"?: AssessmentBudget; readonly "expires_at": string; readonly "external_access_enabled"?: false; readonly "origin": string; readonly "scope_id": string; readonly "stop_conditions": ReadonlyArray<string>; readonly "synthetic_objects"?: ReadonlyArray<SyntheticObject>; };
  export type ScopeAuthority = { readonly "granted_at": string; readonly "granted_by": string; readonly "reference": string; };
  export type SyntheticObject = { readonly "kind": string; readonly "object_id": string; readonly "owner_account_id": string; readonly "synthetic"?: true; readonly "synthetic_marker"?: (string) | (null); };
  export type TestAccount = { readonly "account_id": string; readonly "label": string; readonly "role": string; };
  export type WebsiteScopeCreate = { readonly "confirmed_authority": true; readonly "expectation_basis": string; readonly "expected_owner_only": true; readonly "scope": AssessmentScope; readonly "url": string; };
}
export type WebsiteScopeCreate = WebsiteScopeCreateSchema.WebsiteScopeCreate;


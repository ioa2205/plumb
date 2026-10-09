// Generated from backend JSON Schemas. Run pnpm contracts; never edit by hand.
// Structural types only. Backend validators remain authoritative for evidence and invariants.

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

// CitedExcerpt.schema.json · SHA256 38668ddb0c2caa4c5933c8e898c9799c4302129dd76e3dabb6e2d0bc90bcc8c5
export namespace CitedExcerptSchema {
  export type Exhibit = { readonly "gloss": string; readonly "role": ExhibitRole; readonly "span": SourceSpan; readonly "tag": string; };
  export type ExhibitRole = "evidence" | "source" | "sink" | "guard" | "deviant" | "developer_note";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type CitedExcerpt = { readonly "comments_are_not_evidence"?: true; readonly "end_line": number; readonly "exhibit": Exhibit; readonly "finding_id": string; readonly "lines": ReadonlyArray<string>; readonly "next_offset"?: (number) | (null); readonly "run_id": string; readonly "snapshot_id": string; readonly "start_line": number; readonly "text_is_redacted"?: true; };
}
export type CitedExcerpt = CitedExcerptSchema.CitedExcerpt;

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

// Guard.schema.json · SHA256 3391d129aca6de73ef5f8f9a7aa76dcb61c601bff9167d00221f5feba46e55cb
export namespace GuardSchema {
  export type GuardKind = "authenticated" | "owner" | "tenant" | "role" | "none" | "unknown" | "parameterized" | "allowlisted" | "contained" | "minimized";
  export type GuardMechanism = "dependency" | "decorator" | "query_filter" | "comparison" | "helper_call" | "data_access_layer" | "router" | "proxy_matcher";
  export type SourceSpan = { readonly "content_sha256": string; readonly "end_line": number; readonly "path": string; readonly "snapshot_id": string; readonly "start_line": number; };
  export type Guard = { readonly "canonical": string; readonly "confirmed"?: boolean; readonly "id": string; readonly "kind": GuardKind; readonly "mechanism": GuardMechanism; readonly "object"?: (string) | (null); readonly "role"?: (string) | (null); readonly "snapshot_id": string; readonly "span": SourceSpan; readonly "subject"?: (string) | (null); readonly "via_symbol_id"?: (string) | (null); };
}
export type Guard = GuardSchema.Guard;

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

// LaunchRequest.schema.json · SHA256 e75fc0b15a1df15e280b191ac5c210fe4d20af72e3c6241d46cff4459902d160
export namespace LaunchRequestSchema {
  export type Family = "authorization" | "injection" | "path_traversal" | "nextjs_exposure";
  export type LaunchRequest = { readonly "authorized": true; readonly "families"?: ReadonlyArray<Family>; readonly "inspection_id": string; readonly "limit"?: number; readonly "resources"?: ReadonlyArray<string>; readonly "routes"?: ReadonlyArray<string>; };
}
export type LaunchRequest = LaunchRequestSchema.LaunchRequest;

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

// SetupReadiness.schema.json · SHA256 69513980bc07aa68f2941056fb8c22becfc5ec0d5cbbf6e7d070b86b99a3f51d
export namespace SetupReadinessSchema {
  export type CapabilityEvidence = { readonly "current_engine_acceptance"?: false; readonly "record": string; readonly "scope": string; readonly "sha256": string; };
  export type CapabilityRow = { readonly "category": "language" | "framework" | "family"; readonly "indexed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "indexed_units"?: (number) | (null); readonly "investigated"?: false; readonly "name": string; readonly "parsed": "observed" | "partial" | "unverified" | "not_applicable"; readonly "parsed_units"?: (number) | (null); readonly "reason": string; readonly "runtime_testable"?: false; readonly "units"?: (number) | (null); readonly "workflow_implemented": boolean; };
  export type CapabilityTable = { readonly "evidence": ReadonlyArray<CapabilityEvidence>; readonly "quality_note": string; readonly "registry_sha256": string; readonly "rows": ReadonlyArray<CapabilityRow>; readonly "runtime_note": string; readonly "schema_version"?: 1; readonly "snapshot_id"?: (string) | (null); };
  export type Condition = { readonly "action"?: (string) | (null); readonly "kind": ConditionKind; readonly "message": string; };
  export type ConditionKind = "setup_required" | "model_too_large" | "runner_unavailable" | "stale_source" | "unsupported_framework" | "unreadable_file" | "partial_coverage";
  export type SetupReadiness = { readonly "available_ram_bytes": number; readonly "available_vram_bytes": (number) | (null); readonly "capabilities"?: (CapabilityTable) | (null); readonly "checked_at": string; readonly "conditions": ReadonlyArray<Condition>; readonly "downloads_started"?: false; readonly "inspect_ready": boolean; readonly "limitations": ReadonlyArray<string>; readonly "measured_host": boolean; readonly "memory_fit": boolean; readonly "missing_download_bytes": number; readonly "model_id": string; readonly "model_loaded"?: false; readonly "model_size_bytes": number; readonly "model_verified": boolean; readonly "profile_id": string; readonly "ready": boolean; readonly "required_ram_bytes": number; readonly "required_vram_bytes": number; readonly "requires_large_download_approval": boolean; readonly "runtime_verified": boolean; };
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

// ToolObservation.schema.json · SHA256 03d982822f06ea293f979b2c11fbaae30342ec39028bda400acfad23dc80734d
export namespace ToolObservationSchema {
  export type JsonValue = unknown;
  export type ObservationStatus = "ok" | "error" | "timeout" | "refused";
  export type ToolObservation = { readonly "finished_at": string; readonly "id": string; readonly "inputs": Readonly<Record<string, JsonValue>>; readonly "output_sha256"?: (string) | (null); readonly "question_id"?: (string) | (null); readonly "run_id": string; readonly "started_at": string; readonly "status": ObservationStatus; readonly "tool": string; readonly "tool_version": string; };
}
export type ToolObservation = ToolObservationSchema.ToolObservation;


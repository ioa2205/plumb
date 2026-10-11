// Synthetic display responses only. No model, host probe, website collection or lab.
import { createHash } from "node:crypto";

const digest = value => createHash("sha256").update(value).digest("hex");

export function conversationFixtures({inspection, saved, assessment, codePages}) {
  const views = new Map();
  let sequence = 0;
  const targets = new Map([
    [inspection.inspection_id, "inspection"],
    [saved.run.id, "review"],
    [assessment.scope.assessment_id, "assessment"],
  ]);
  function evidence(target) {
    if (target.target_kind === "assessment") return assessment.artifacts
      .filter(artifact => artifact.kind === "request_response")
      .slice(0, 2).map((artifact, index) => ({
        reference_id: `R${String(index + 1).padStart(3, "0")}`,
        label: "Synthetic imported response body",
        quote: artifact.fields["response.body"], source: null,
        observation: {artifact_id: artifact.artifact_id, field: "response.body", sha256: digest(artifact.fields["response.body"])},
      }));
    const page = codePages.find(page => page.citation.snapshot_id === (target.target_kind === "inspection" ? inspection.snapshot_id : saved.run.snapshot_id));
    if (!page) throw new Error("The synthetic conversation needs an exact saved source page");
    return [{reference_id: "R001", label: "Saved source excerpt in a synthetic conversation display", source: page.citation, observation: null,
      quote: page.lines.slice(page.citation.start_line - page.start_line, page.citation.end_line - page.start_line + 1).join("\n")}];
  }
  return function response(path, method, body) {
    if (path === "/api/conversations" && method === "POST") {
      if (!body || targets.get(body.target_id) !== body.target_kind) return null;
      const value = {...body, conversation_id: `conversation-${(++sequence).toString(16).padStart(32, "0")}`, state: "idle", turns: [], message: "Synthetic conversation UI fixture. No model was loaded.", confidentiality: "private_local"};
      views.set(value.conversation_id, value); return structuredClone(value);
    }
    const match = /^\/api\/conversations\/(conversation-[0-9a-f]{32})(?:\/(ask|cancel))?$/.exec(path);
    if (!match || !views.has(match[1])) return null;
    const value = views.get(match[1]);
    if (match[2] === "cancel" && method === "POST") {value.state = "canceled"; return structuredClone(value);}
    if (match[2] === "ask" && method === "POST") {
      const refs = evidence(value); const followup = value.turns.length > 0;
      value.turns.push({prompt: body.prompt,
        answer: `Synthetic UI answer; no inference. ${followup ? "This follow-up retains the same loaded evidence and its limitations." : "The answer is bound to the exact saved source or reviewed observation fields below."} A question executes no collection, review or state change.`,
        evidence: refs, unknowns: ["Synthetic appearance fixture; fresh conversation/model quality has not been accepted.", "Runtime reproduction and broader project security are not established by this answer."],
        generated_by: "local_model", evidence_sha256: digest(JSON.stringify(refs)), authorization_granted: false, actions_executed: false, verdict_changed: false});
      value.state = "completed"; value.message = "Synthetic UI conversation saved; no model or lab started.";
    }
    return structuredClone(value);
  };
}

import { test } from "node:test";
import assert from "node:assert/strict";
import { typeExpression, generateContracts, renderContracts } from "./contracts.mjs";

test("generated API contracts are current and include every known schema", () => {
  generateContracts(true);
  const text = renderContracts();
  assert.equal((text.match(/export namespace /g)||[]).length,44);
  for (const name of ["DispositionUpdate","DispositionDecision","ReviewRun","Finding","RunEvent","ApplicationMap","FindingPage","CaseDetail","CitedExcerpt","PeerExcerpt","SnapshotCodePage"]) assert.ok(text.includes(`export type ${name} = ${name}Schema.${name};`));
});

test("compiler preserves references, nullable/default fields, literals, arrays and rejects unsupported constructs", () => {
  const defs={State:{enum:["live","saved"]}};
  const result=typeExpression({type:"object",properties:{state:{$ref:"#/$defs/State"},maybe:{anyOf:[{type:"string"},{type:"null"}]},values:{type:"array",items:{type:"integer"}}},required:["state"]},defs);
  assert.match(result,/readonly "state": State/);
  assert.match(result,/readonly "maybe"\?: \(string\) \| \(null\)/);
  assert.match(result,/ReadonlyArray<number>/);
  assert.equal(typeExpression({const:"completed"}), '"completed"');
  assert.equal(typeExpression({}), "unknown");
  assert.equal(typeExpression({enum:["live","saved"]}), '"live" | "saved"');
  for(const node of [{$ref:"https://external.invalid/schema"},{$ref:"#/$defs/Missing"},{type:"unknown"},{type:"object",properties:{x:{type:"string"}},additionalProperties:{type:"string"}}]) assert.throws(()=>typeExpression(node,defs));
});

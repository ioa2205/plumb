import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateCapabilities } from "../lib/capability-data.ts";

const snapshot="a".repeat(64);
const registry=JSON.parse(readFileSync(new URL("../../backend/capabilities.json",import.meta.url),"utf8"));
const table=()=>({schema_version:1,registry_sha256:"b".repeat(64),snapshot_id:snapshot,
  rows:[{category:"language",name:"python",units:2,parsed_units:1,indexed_units:1,parsed:"partial",indexed:"partial",workflow_implemented:false,investigated:false,runtime_testable:false,reason:"One malformed source file."}],
  evidence:registry.evidence,quality_note:"Current acceptance unrun.",runtime_note:"No isolated runner."});
test("partial source observations retain denominators; legacy capability omission is readable",()=>{
  validateCapabilities(table(),snapshot,{python:2},{});
  validateCapabilities(undefined,snapshot);
});
test("capability transport refuses false accuracy, mixed snapshots and contradictory counts",()=>{
  for(const update of [{investigated:true},{runtime_testable:true},{parsed:"observed"},{units:3},{parsed_units:3}]){
    const value=table();Object.assign(value.rows[0],update);
    assert.throws(()=>validateCapabilities(value,snapshot,{python:2},{}));
  }
  assert.throws(()=>validateCapabilities(table(),"c".repeat(64)));
  const duplicate=table();duplicate.rows.push({...duplicate.rows[0]});
  assert.throws(()=>validateCapabilities(duplicate,snapshot));
});

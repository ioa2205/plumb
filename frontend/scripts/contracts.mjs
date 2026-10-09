import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const schemas = fileURLToPath(new URL("../../backend/contracts/schemas/", import.meta.url));
const destination = fileURLToPath(new URL("../generated/", import.meta.url));
const identifier = name => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);

export function typeExpression(node, definitions = {}) {
  if (node === true) return "unknown";
  if (node === false) return "never";
  if (!node || typeof node !== "object") throw new Error("Unsupported schema node");
  if (Object.keys(node).length === 0) return "unknown";
  if (node.$ref) {
    const name = node.$ref.replace(/^#\/\$defs\//, "");
    if (node.$ref !== `#/$defs/${name}` || !identifier(name) || !Object.hasOwn(definitions,name)) throw new Error("Unknown/local-only schema reference");
    return name;
  }
  if (Object.hasOwn(node,"const")) return JSON.stringify(node.const);
  if (node.enum) return node.enum.map(item => JSON.stringify(item)).join(" | ");
  if (node.anyOf || node.oneOf) return (node.anyOf || node.oneOf).map(item => `(${typeExpression(item, definitions)})`).join(" | ");
  switch(node.type) {
    case "string": return "string";
    case "integer": case "number": return "number";
    case "boolean": return "boolean";
    case "null": return "null";
    case "array": return `ReadonlyArray<${typeExpression(node.items,definitions)}>`;
    case "object": {
      const props = Object.entries(node.properties || {});
      const fields = props.map(([key,value]) => `readonly ${JSON.stringify(key)}${node.required?.includes(key) ? "" : "?"}: ${typeExpression(value,definitions)};`).join(" ");
      if (node.additionalProperties && node.additionalProperties !== false) {
        if (props.length) throw new Error("Mixed indexed objects require a deliberate compiler extension");
        return `Readonly<Record<string, ${typeExpression(node.additionalProperties,definitions)}>>`;
      }
      return fields ? `{ ${fields} }` : "Readonly<Record<string, never>>";
    }
    default: throw new Error(`Unsupported schema type: ${String(node.type)}`);
  }
}

export function renderContracts(directory = schemas) {
  let output = "// Generated from backend JSON Schemas. Run pnpm contracts; never edit by hand.\n// Structural types only. Backend validators remain authoritative for evidence and invariants.\n\n";
  for (const file of readdirSync(directory).filter(name => name.endsWith(".schema.json")).sort()) {
    const bytes = readFileSync(join(directory,file));
    const schema = JSON.parse(bytes.toString("utf8"));
    const name = file.replace(".schema.json","");
    if (!identifier(name) || schema.title !== name || schema.$defs?.[name]) throw new Error("Invalid contract name");
    const definitions = schema.$defs || {};
    output += `// ${file} · SHA256 ${createHash("sha256").update(bytes).digest("hex")}\nexport namespace ${name}Schema {\n`;
    for (const [key,node] of Object.entries(definitions)) {
      if (!identifier(key)) throw new Error("Invalid definition name");
      output += `  export type ${key} = ${typeExpression(node,definitions)};\n`;
    }
    output += `  export type ${name} = ${typeExpression(schema,definitions)};\n}\nexport type ${name} = ${name}Schema.${name};\n\n`;
  }
  return output;
}

export function generateContracts(check = false) {
  const files = {"contracts.ts":renderContracts()};
  files["bound-policy.schema.json"]=readFileSync(join(schemas,"BoundPolicy.schema.json"),"utf8");
  files["disposition-decision.schema.json"]=readFileSync(join(schemas,"DispositionDecision.schema.json"),"utf8");
  files["capability-table.schema.json"]=readFileSync(join(schemas,"CapabilityTable.schema.json"),"utf8");
  for(const [file,contract] of [["source-check","SourceCheck"],["setup-readiness","SetupReadiness"],["inspection-view","InspectionView"]]) files[`${file}.schema.json`]=readFileSync(join(schemas,`${contract}.schema.json`),"utf8");
  for(const [file,contract] of [["run-history","RunHistory"],["run-comparison","RunComparison"],["project-page","ProjectPage"],["project-rule","ProjectRule"],["project-excerpt","ProjectExcerpt"],["review-page","ReviewPage"],["finding-list","FindingList"],["run-event","RunEvent"],["review-run","ReviewRun"],["finding-page","FindingPage"],["case-detail","CaseDetail"],["cited-excerpt","CitedExcerpt"],["peer-excerpt","PeerExcerpt"],["snapshot-code-page","SnapshotCodePage"]]) files[`${file}.schema.json`]=readFileSync(join(schemas,`${contract}.schema.json`),"utf8");
  if (!check) mkdirSync(destination,{recursive:true});
  for (const [name,text] of Object.entries(files)) {
    const path = join(destination,name);
    if (check) { if(readFileSync(path,"utf8") !== text) throw new Error(`Stale generated contract: ${name}`); }
    else writeFileSync(path,text);
  }
}
if(process.argv[1] === fileURLToPath(import.meta.url)) generateContracts(process.argv.includes("--check"));

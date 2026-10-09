import type {CapabilityTable as CapabilityRecord} from "../generated/contracts";
import styles from "./CapabilityTable.module.css";

const words=(value:string)=>value.replaceAll("_"," ");
export function CapabilityTable({value}:{value?:CapabilityRecord|null}){
  if(!value)return <p>Capability acceptance was not recorded in this saved view.</p>;
  return <details className={styles.capabilities}><summary>Source support and acceptance</summary>
    <p>{value.quality_note}</p>
    <table><caption>Capability levels for {value.snapshot_id?"this frozen snapshot":"the implementation; no source inspected yet"}</caption>
      <thead><tr><th scope="col">Scope</th><th scope="col">Parsed</th><th scope="col">Indexed</th><th scope="col">Investigated</th><th scope="col">Runtime-testable</th></tr></thead>
      <tbody>{value.rows.map(row=><tr key={`${row.category}/${row.name}`}><th scope="row">{words(row.name)}<span>{row.category}{row.workflow_implemented?" · workflow implemented":""}</span></th><td>{words(row.parsed)}{row.units!==null&&row.units!==undefined&&<> · {row.parsed_units}/{row.units}</>}</td><td>{words(row.indexed)}{row.units!==null&&row.units!==undefined&&<> · {row.indexed_units}/{row.units}</>}</td><td>Unverified</td><td>Unavailable</td></tr>)}</tbody>
    </table><p>{value.runtime_note}</p>
    <ul aria-label="Recorded capability evidence">{value.evidence.map(e=><li key={e.record}><code>{e.record}</code><p>{e.scope}</p><details><summary>Evidence identity</summary><code>SHA256 {e.sha256}</code><p>Historical observation; current engine acceptance is unrun.</p></details></li>)}</ul>
  </details>;
}

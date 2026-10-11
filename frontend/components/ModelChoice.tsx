"use client";

import { useEffect, useId, useState } from "react";
import type { ModelCatalog } from "../generated/contracts";
import { fetchReadiness } from "../lib/setup-data";
import { profileChoice } from "../lib/model-choices";
import styles from "./ModelChoice.module.css";

export function ModelChoice({profile, onChange, catalog: supplied, disabled = false}: {profile: string; onChange: (value: string) => void; catalog?: ModelCatalog | null; disabled?: boolean}) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(supplied ?? null);
  const [message, setMessage] = useState("");
  const id = useId();
  useEffect(() => { if (supplied) setCatalog(supplied); }, [supplied]);
  useEffect(() => {
    if (supplied) return;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 90000);
    fetchReadiness(controller.signal).then(readiness => {if (!controller.signal.aborted) {setCatalog(readiness.model_catalog ?? null); if (!readiness.model_catalog) setMessage("Model choices are unavailable. Read plumb doctor in the terminal.");}}).catch(error => {if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "Model choices could not be read.");}).finally(() => clearTimeout(timer));
    return () => {controller.abort(); clearTimeout(timer);};
  }, [supplied]);
  const selected = catalog ? profileChoice(catalog, profile === "auto" ? catalog.recommended_profile ?? "" : profile) : null;
  const model = catalog?.models.find(value => value.profiles.some(choice => choice.profile_id === selected?.profile_id));
  return <details className={styles.choices}><summary>Local model choice</summary>
    <p>Automatic uses recorded review evidence and the hardware that fits now. Each launch checks memory again.</p>
    <label htmlFor={id}>Model and runtime profile</label><select id={id} value={profile} onChange={event => onChange(event.target.value)} disabled={disabled || !catalog} aria-describedby={`${id}-limits`}>
      <option value="auto">Automatic{catalog?.recommended_profile ? ` · ${catalog.recommended_profile}` : " · unavailable"}</option>
      {catalog?.models.flatMap(value => value.profiles.map(choice => <option key={choice.profile_id} value={choice.profile_id}>{value.family} · {choice.backend} · {choice.quality_state === "untested" ? "untested quality" : "scoped review evidence"}{!choice.launch_available ? " · needs attention" : ""}</option>))}
    </select>
    <p id={`${id}-limits`}>Selection starts no model or download. Untested choices require an explicit selection and a first-use check. Larger models have no assumed quality advantage.</p>
    {catalog && <><p className={styles.meta}>Current free RAM: {gb(catalog.available_ram_bytes)}. Dedicated VRAM: {catalog.available_vram_bytes === null ? "unknown" : gb(catalog.available_vram_bytes)}.</p>
      {selected && model && <div className={styles.details}><h3>{model.family} · {model.quantization}</h3><p>{model.verified_installed ? "Verified local model" : "Model missing or unverified"} · {gb(model.size_bytes)}{!model.verified_installed && model.requires_download_approval ? " · download approval required" : ""}.</p>
        <p>{selected.hardware_compatible ? "Compatible hardware" : "Hardware unavailable"}; {selected.memory_fit ? "memory fits now" : "memory does not fit now"}. Requires {gb(selected.required_ram_bytes)} RAM{selected.required_vram_bytes ? ` and ${gb(selected.required_vram_bytes)} dedicated VRAM` : ""}.</p>
        <p>First-use check: {selected.first_use_check}. {selected.first_use_check === "pending" ? "Runs before the first review with this profile." : ""}</p><p>{selected.quality_note}</p>
        {selected.quality_records.length > 0 && <p className={styles.meta}>Recorded evidence: {selected.quality_records.map(record => record.path).join("; ")}</p>}
        {!!selected.conditions.length && <ul>{selected.conditions.map((condition, index) => <li key={index}>{condition}</li>)}</ul>}
      </div>}
      {!!catalog.models.filter(value => !value.profiles.length).length && <details><summary>Unavailable candidates</summary><ul>{catalog.models.filter(value => !value.profiles.length).map(value => <li key={value.model_id}>{value.family}: {value.unavailable_reason} Untested quality.</li>)}</ul></details>}
      <details><summary>Automatic selection basis</summary><p>{catalog.selection_basis}</p></details>
    </>}
    <p role="status">{message}</p>
  </details>;
}
const gb = (value: number) => `${(value / 1_000_000_000).toFixed(2)} GB`;

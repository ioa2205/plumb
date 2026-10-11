import type { ModelCatalog, ModelProfileChoice } from "../generated/contracts";

export class ModelChoiceError extends Error {}
export function validProfile(value: unknown): value is string { return typeof value === "string" && /^(auto|[a-z][a-z0-9._-]{0,127})$/.test(value); }
export function validateModelCatalog(value: ModelCatalog): ModelCatalog {
  const profiles = value.models.flatMap(model => model.profiles);
  if (new Set(value.models.map(model => model.model_id)).size !== value.models.length || new Set(profiles.map(profile => profile.profile_id)).size !== profiles.length
      || [value.selected_profile, value.recommended_profile].some(id => id !== null && !profiles.some(profile => profile.profile_id === id))
      || value.models.some(model => model.requires_download_approval !== (model.size_bytes > 500_000_000) || !model.profiles.length && !model.unavailable_reason || !model.verified_installed && model.profiles.some(profile => profile.launch_available))
      || profiles.some(profile => !validProfile(profile.profile_id) || profile.automatic_eligible !== (profile.quality_state === "recorded_scoped") || (profile.quality_state === "recorded_scoped") !== !!profile.quality_records.length
        || profile.memory_fit !== (value.available_ram_bytes >= profile.required_ram_bytes && (profile.required_vram_bytes === 0 || profile.available_vram_bytes !== null && profile.available_vram_bytes >= profile.required_vram_bytes))
        || profile.launch_available && !(profile.hardware_compatible && profile.memory_fit && profile.runtime_verified && profile.runtime_compatible === true && profile.first_use_check !== "failed"))
      || value.recommended_profile && !profiles.find(profile => profile.profile_id === value.recommended_profile)?.automatic_eligible) throw new ModelChoiceError("Model choices disagree with their recorded quality or launch requirements.");
  return value;
}
export function profileChoice(catalog: ModelCatalog, id: string): ModelProfileChoice | null { return catalog.models.flatMap(model => model.profiles).find(profile => profile.profile_id === id) ?? null; }

"""Bounded browser/CLI model catalog projected from the existing read-only doctor."""

from datetime import UTC, datetime
from typing import Any

from backend.contracts.model_choices import ModelCatalog, ModelChoice, ModelProfileChoice
from backend.model_quality import evidence

SELECTION_BASIS = (
    "Automatic selection requires recorded scoped development quality, compatible "
    "hardware and the current memory/asset/runtime gates. Prefer the measured "
    "hardware profile when available, then its CPU profile. Untested alternatives "
    "require an explicit choice and their own first-use check. Model size never "
    "ranks security quality. If no eligible profile is ready, setup shows the "
    "eligible compatible choice and refuses launch until its gates pass."
)


def catalog(report: dict[str, Any]) -> ModelCatalog:
    choices = []
    for model in report["model_candidates"]:
        profiles = []
        for profile in report["profiles"]:
            if profile["model_id"] != model["id"]:
                continue
            quality = evidence(profile)
            profiles.append(
                ModelProfileChoice(
                    profile_id=profile["id"],
                    backend=profile["backend"],
                    hardware_compatible=profile["compatible_measured_host"],
                    memory_fit=profile["estimated_memory_fit"],
                    required_ram_bytes=profile["host_required_bytes"],
                    required_vram_bytes=profile["device_required_bytes"],
                    available_vram_bytes=profile["dedicated_free_bytes"],
                    runtime_verified=profile["runtime_verified"],
                    runtime_compatible=profile["runtime_compatible"],
                    first_use_check=profile["first_use_check"],
                    launch_available=profile["ready"],
                    **quality,
                    conditions=profile["messages"],
                )
            )
        choices.append(
            ModelChoice(
                model_id=model["id"],
                family=model.get("family", model["id"]),  # Older doctor records omit the label.
                quantization=model["quantization"],
                size_bytes=model["size_bytes"],
                verified_installed=model["verified_installed"],
                requires_download_approval=model["requires_download_approval"],
                profiles=profiles,
                unavailable_reason=None
                if profiles
                else (
                    "No launch profile: memory requirement or runtime support "
                    "has not been measured."
                ),
            )
        )
    return ModelCatalog(
        checked_at=datetime.now(UTC),
        selected_profile=report["selected_profile"],
        recommended_profile=report["recommended_profile"],
        selection_basis=SELECTION_BASIS,
        available_ram_bytes=report["inventory"]["memory"]["available_bytes"],
        available_vram_bytes=report["inventory"]["dedicated_free_bytes"],
        models=choices,
    )

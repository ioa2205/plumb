"""Curated, pinned development evidence for model selection; no comparative scores.

These records are historical source-review evidence, not a current-engine or web
assessment qualification. Adding a model requires a reviewed actual result, never
a first-use format/canary pass or a memory estimate (ADR-0026).
"""

from typing import Any

from backend import cpu_profile, vulkan_profile

RECORDS: dict[str, tuple[str, str]] = {
    "mx350-vulkan-8k": (
        "docs/results/2026-10-08-m7.8a-raw/report.json",
        "9076a57cb8727ba1d2b21f25ee4e3e05cdab9c1ceabf906935686b1c46638a0f",
    ),
    "cpu-8k": (
        "docs/results/2026-10-10-a1-cpu-profile-review/report.json",
        "893e6a2a22bf24a410f1b363f4ba19e703fbe7c1fd8b1463d5dc7d5b6be2fdd7",
    ),
}
LIMIT = (
    "Historical owned Tandir source review: receipt Supported, protected invoice "
    "Rejected. No cross-model comparison or general accuracy qualification. "
    "Fresh web-observation quality and other failed/unrun gates remain unmet."
)


def evidence(profile: dict[str, Any]) -> dict[str, Any]:
    """Only the exact model/runtime/profile identities retain curated evidence."""
    record = RECORDS.get(profile["id"])
    offload = profile["id"] == "mx350-vulkan-8k"
    expected = {
        "backend": "vulkan" if offload else cpu_profile.BACKEND,
        "context": 8192,
        "threads": 4,
        "batch": 256 if offload else cpu_profile.BATCH,
        "microbatch": 64 if offload else cpu_profile.MICROBATCH,
        "offload_layers": 99 if offload else 0,
        "host_required_bytes": (
            vulkan_profile.REQUIREMENT.host_bytes if offload else cpu_profile.REQUIRED_BYTES
        ),
        "device_required_bytes": vulkan_profile.REQUIREMENT.device_bytes if offload else 0,
        "device": vulkan_profile.DEVICE if offload else "",
        "device_name": vulkan_profile.DEVICE_NAME if offload else "",
        "extra_args": list(vulkan_profile.EXTRA_ARGS) if offload else [],
        "stateless": True,
        "reasoning": "off",
    }
    eligible = (
        record is not None
        and profile["model_id"] == vulkan_profile.MODEL_ID
        and profile["model_sha256"] == vulkan_profile.MODEL_SHA256
        and profile["runtime_commit"] == vulkan_profile.BUILD_COMMIT
        and all(profile.get(key) == value for key, value in expected.items())
    )
    return {
        "quality_state": "recorded_scoped" if eligible else "untested",
        "quality_records": [{"path": record[0], "sha256": record[1]}] if eligible else [],
        "quality_note": LIMIT
        if eligible
        else (
            "Untested for Plumb review quality; a memory estimate or first-use "
            "format/leak check does not establish security judgment quality."
        ),
        "automatic_eligible": eligible,
    }

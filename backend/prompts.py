"""A bounded interpreter over existing source IDs, and cited saved-case answers."""

import hashlib
import re
from collections.abc import Sequence
from typing import Literal

from backend.contracts.common import Family
from backend.contracts.prompts import SourcePromptRequest, SourcePromptResolution
from backend.redaction import Redactor
from backend.review import Review, write_json
from backend.saved_reports import load
from backend.settings import Settings
from backend.source_binding import inspection

_FAMILIES: tuple[tuple[Family, tuple[str, ...]], ...] = (
    (Family.AUTHORIZATION, ("ownership", "owner", "authorization", "tenant", "access")),
    (Family.INJECTION, ("injection", "sql", "command")),
    (Family.PATH_TRAVERSAL, ("traversal", "filesystem")),
    (Family.NEXTJS_EXPOSURE, ("exposure", "serialization", "nextjs")),
)
_WORDS = frozenset(
    [
        "review",
        "check",
        "investigate",
        "inspect",
        "this",
        "the",
        "project",
        "code",
        "for",
        "problems",
        "issues",
        "security",
        "weaknesses",
        "risky",
        "risks",
        "vulnerability",
        "vulnerabilities",
        "ownership",
        "owner",
        "authorization",
        "tenant",
        "access",
        "injection",
        "sql",
        "command",
        "traversal",
        "filesystem",
        "exposure",
        "serialization",
        "nextjs",
        "all",
        "source",
        "routes",
        "route",
        "orders",
        "order",
        "on",
        "in",
        "and",
        "please",
        "potential",
        "local",
        "scoped",
        "path",
    ]
)


def resolve_source_prompt(
    prompt: str,
    target_id: str,
    resources: Sequence[str],
    routes: Sequence[str],
    *,
    limit: int = 5,
    redactor: Redactor | None = None,
) -> SourcePromptResolution:
    """Interpret explicit supported focus. Unknown language never silently broadens scope."""
    if not 1 <= len(prompt) <= 4096 or not 1 <= limit <= 20:
        raise ValueError("Use a bounded prompt and question limit")
    redacted = (redactor or Redactor.configured()).text(prompt).strip()
    if not redacted:
        raise ValueError("Prompt is empty")
    identifier = hashlib.sha256(f"{target_id}:{redacted}:{limit}".encode()).hexdigest()[:24]
    tokens = set(re.findall(r"[a-z_]+", redacted.lower()))
    families = [family for family, words in _FAMILIES if tokens.intersection(words)]
    chosen_resources = [
        resource
        for resource in resources
        if any(word in tokens for word in (resource.lower(), resource.lower().removesuffix("s")))
    ]
    requested_routes = re.findall(r"/[A-Za-z0-9_{}./:-]+", redacted)
    known_words = _WORDS | {
        word
        for resource in resources
        for word in (resource.lower(), resource.lower().removesuffix("s"))
    }
    route_words = set(re.findall(r"[a-z_]+", " ".join(requested_routes).lower()))
    status: Literal["resolved", "clarification_required", "refused"] = "resolved"
    clarification = None
    if (
        redacted != prompt.strip()
        or any(ord(char) < 32 for char in redacted)
        or "http" in redacted.lower()
        or tokens - known_words - route_words
        or any(route not in routes for route in requested_routes)
    ):
        status = "refused"
        clarification = (
            "Use supported source focus and exact discovered resources/routes. "
            "Prompts cannot authorize websites, execute actions or change verdicts."
        )
    elif not families:
        status = "clarification_required"
        clarification = "Specify authorization, injection, path traversal or Next.js exposure."
    elif chosen_resources and families != [Family.AUTHORIZATION]:
        status = "clarification_required"
        clarification = "Resource filters apply to authorization only; select one focus."
    return SourcePromptResolution(
        target_id=target_id,
        task_id="source-task-" + identifier,
        prompt=redacted,
        families=families,
        resources=chosen_resources,
        routes=requested_routes,
        limit=limit,
        status=status,
        clarification=clarification,
    )


def resolve_inspected(settings: Settings, request: SourcePromptRequest) -> SourcePromptResolution:
    """Use the registered frozen map; reading a prompt does not launch a model."""
    _, snapshot_id = inspection(settings, request.inspection_id)
    review = Review(settings, snapshot_id)
    try:
        task = resolve_source_prompt(
            request.prompt,
            request.inspection_id,
            sorted({site.resource for site in review.map.access_sites}),
            sorted({entry.route for entry in review.map.entries if entry.route}),
            limit=request.limit,
            redactor=Redactor.configured(settings),
        )
    finally:
        review.close()
    directory = settings.cache_dir / "prompt-tasks"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / f"{task.task_id}.json", task.model_dump(mode="json"))
    return task


def ask_saved(settings: Settings, run_id: str, prompt: str) -> dict[str, object]:
    """Answer from validated saved conclusions and exact existing exhibits, without inference."""
    if not 1 <= len(prompt) <= 4096:
        raise ValueError("Use a bounded saved-case question")
    instruction = Redactor.configured(settings).text(prompt)
    selected = re.findall(r"\bF-\d{2,}\b", instruction, flags=re.IGNORECASE)
    if len(selected) != 1 or not re.search(
        r"\b(explain|evidence|limitations|report|finding)\b", instruction, re.IGNORECASE
    ):
        raise ValueError("Name one saved finding, e.g. Explain F-01 and its limitations")
    bundle, path = load(settings, run_id)
    matches = [finding for finding in bundle.findings if finding.display_id == selected[0].upper()]
    if len(matches) != 1:
        raise ValueError("No saved finding has this ID")
    finding = matches[0]
    # The full saved case preserves the factual claim, counterevidence and unknowns. The
    # report loader already validates all source citations against immutable source.
    answer = {
        "run_id": run_id,
        "prompt": instruction,
        "finding": finding.model_dump(mode="json"),
        "report_path": str(path),
        "limitations": bundle.limitations,
        "generated_by": "saved_evidence",
        "network_activity": False,
        "authorization_granted": False,
    }
    directory = settings.cache_dir / "prompt-tasks"
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(f"{run_id}:{instruction}".encode()).hexdigest()[:24]
    write_json(directory / f"saved-answer-{identity}.json", answer)
    return answer

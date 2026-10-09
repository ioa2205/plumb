"""Shared types for Plumb's contracts (PROJECT_PLAN §6)."""

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


class Contract(BaseModel):
    """Base for every persisted entity: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Line = Annotated[int, Field(ge=1)]


def _relative_posix_path(value: str) -> str:
    """A path inside the snapshot root: forward slashes, no root, no drive, no '..'."""
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"not a snapshot-relative POSIX path: {value!r}")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.drive or windows.root:
        raise ValueError(f"absolute path not allowed: {value!r}")
    if any(part in ("..", ".") for part in value.split("/")) or "//" in value:
        raise ValueError(f"path must be normalized and stay inside the root: {value!r}")
    return value


RelPath = Annotated[str, AfterValidator(_relative_posix_path)]


class Language(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    JAVASCRIPT = "javascript"


class Framework(StrEnum):
    FASTAPI = "fastapi"
    NEXTJS = "nextjs"


class LinkStatus(StrEnum):
    """How firmly a static link between two places in the code is established."""

    RESOLVED = "resolved"  # language service uniquely identifies a snapshot definition
    INFERRED = "inferred"  # static import/lexical fallback, without type-aware confirmation
    UNRESOLVED = "unresolved"  # dynamic, external or ambiguous; kept visible, never dropped


class Family(StrEnum):
    """Vulnerability families investigated in depth (PROJECT_PLAN §4)."""

    AUTHORIZATION = "authorization"  # A: object- and tenant-level, CWE-639/862/863
    INJECTION = "injection"  # B: SQL and OS command, CWE-89/78
    PATH_TRAVERSAL = "path_traversal"  # C: CWE-22
    NEXTJS_EXPOSURE = "nextjs_exposure"  # D: CWE-200/862


class InputOrigin(StrEnum):
    """Where a value comes from, as answered by the ``input_origin`` question."""

    PATH = "path"
    QUERY = "query"
    BODY = "body"
    HEADER = "header"
    SESSION = "session"
    CONSTANT = "constant"
    UNKNOWN = "unknown"

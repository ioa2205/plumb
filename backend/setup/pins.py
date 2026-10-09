"""Pin manifests for llama.cpp builds and model files.

The TOML files in ``pins/`` are the single source of truth for what Plumb
downloads. Hashes come from the publisher (GitHub asset digests, Hugging Face
LFS hashes) and are re-checked after every download.
"""

import tomllib
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PIN_DIR = Path(__file__).with_name("pins")
LLAMA_CPP_PINS = PIN_DIR / "llama_cpp.toml"
MODEL_PINS = PIN_DIR / "models.toml"
OPENGREP_PINS = PIN_DIR / "opengrep.toml"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$")]
FileName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


def _require_https_host(url: str, allowed: set[str]) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in allowed:
        raise ValueError(f"{url!r} is not an https URL on {sorted(allowed)}")
    return url


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Asset(_Frozen):
    name: FileName
    url: str
    sha256: Sha256
    size: int = Field(gt=0)

    @field_validator("url")
    @classmethod
    def _github_only(cls, url: str) -> str:
        return _require_https_host(url, {"github.com"})


class Variant(_Frozen):
    description: str
    assets: list[Asset] = Field(min_length=1)


class LlamaCppPin(_Frozen):
    release: str
    build: Annotated[str, StringConstraints(pattern=r"^b\d+$")]
    commit: GitRevision
    published: date
    variants: dict[Slug, Variant] = Field(min_length=1)


class OpengrepPin(_Frozen):
    release: str
    commit: GitRevision
    published: date
    asset: Asset


class ModelPin(_Frozen):
    id: Slug
    family: str
    role: str
    repo: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    revision: GitRevision
    file: FileName
    sha256: Sha256
    size: int = Field(gt=0)
    quantization: str
    license: str
    license_source: str
    base_model: str
    # f16 KV cache bytes per context token, computed from the published model
    # configuration (HARDWARE.md, "KV cache"). None until a source exists.
    kv_bytes_per_token: int | None = Field(default=None, gt=0)

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.file}"


class ModelPins(_Frozen):
    models: list[ModelPin] = Field(min_length=1)

    @field_validator("models")
    @classmethod
    def _unique_ids(cls, models: list[ModelPin]) -> list[ModelPin]:
        ids = [m.id for m in models]
        if len(ids) != len(set(ids)):
            raise ValueError("model ids must be unique")
        return models

    def get(self, model_id: str) -> ModelPin:
        for model in self.models:
            if model.id == model_id:
                return model
        raise KeyError(f"unknown model id {model_id!r}; known: {[m.id for m in self.models]}")


def load_llama_cpp_pin(path: Path = LLAMA_CPP_PINS) -> LlamaCppPin:
    return LlamaCppPin.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


def load_model_pins(path: Path = MODEL_PINS) -> ModelPins:
    return ModelPins.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


def load_opengrep_pin(path: Path = OPENGREP_PINS) -> OpengrepPin:
    return OpengrepPin.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))

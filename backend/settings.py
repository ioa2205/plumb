"""Process settings, read from ``PLUMB_*`` environment variables."""

import sys
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.user_config import default_data_dir

DEFAULT_PORT = 8700  # the Tandir lab uses 8701 and 8702
DEFAULT_NODE_BINARY = Path(
    r"C:\Program Files\nodejs\node.exe" if sys.platform == "win32" else "/usr/bin/node"
)


class Settings(BaseSettings):
    """Settings for one Plumb process.

    Models, llama.cpp builds, and caches live outside the repository in
    ``data_dir`` (``PLUMB_DATA_DIR``). A bounded per-user location is read only
    when no explicit argument/environment overrides it. Loading creates no files.
    """

    model_config = SettingsConfigDict(env_prefix="PLUMB_", env_ignore_empty=True, frozen=True)

    data_dir: Path = Field(default_factory=default_data_dir)
    node_binary: Path = DEFAULT_NODE_BINARY
    # The local API's loopback port. The address itself is not a setting: it is always 127.0.0.1.
    port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    # A lasting profile choice for the terminal and the browser; "auto" follows plumb doctor.
    profile: str = Field(default="auto", pattern=r"^[a-z0-9][a-z0-9._-]*$")
    peer_min_peers: int = Field(default=3, ge=1)
    peer_min_share: float = Field(default=0.75, gt=0, le=1)
    # JSON array in PLUMB_REDACTION_SECRETS; never show values in settings diagnostics.
    redaction_secrets: tuple[SecretStr, ...] = Field(default=(), repr=False, exclude=True)

    @field_validator("redaction_secrets")
    @classmethod
    def _nonempty_secrets(cls, values: tuple[SecretStr, ...]) -> tuple[SecretStr, ...]:
        if any(not value.get_secret_value() for value in values):
            raise ValueError("redaction values cannot be empty")
        return values

    @field_validator("data_dir", "node_binary")
    @classmethod
    def _require_absolute(cls, value: Path) -> Path:
        # A relative path would put gigabytes of models under whatever the
        # working directory is, usually the repository itself.
        if not value.is_absolute():
            raise ValueError(f"setting must be an absolute path, got {str(value)!r}")
        return value

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def llama_cpp_dir(self) -> Path:
        return self.data_dir / "llama.cpp"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

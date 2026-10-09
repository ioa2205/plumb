"""One bounded per-user data-location preference; never reads target configuration."""

import os
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

LEGACY_DATA_DIR = Path(r"D:\plumb-data")
LIMIT = 4096
ROOT = Path(__file__).resolve().parents[1]


def user_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not base.is_absolute():
        raise ValueError("The per-user application data directory must be an absolute path")
    return base / "Plumb"


class DataLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    data_dir: Path

    @field_validator("data_dir")
    @classmethod
    def absolute_external(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("remembered data directory must be an absolute path")
        if value.resolve().is_relative_to(ROOT):
            raise ValueError("remembered data directory must be outside the Plumb installation")
        return value


def location_file() -> Path:
    return user_dir() / "settings.json"


def read_location() -> DataLocation | None:
    path = location_file()
    try:
        if path.is_symlink():
            raise ValueError("Per-user preferences must not be a symbolic link")
        with path.open("rb") as source:
            content = source.read(LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(content) > LIMIT:
        raise ValueError("Per-user preferences exceed the 4096-byte limit")
    try:
        return DataLocation.model_validate_json(content)
    except ValueError:
        raise ValueError(
            "Invalid per-user Plumb preferences; use PLUMB_DATA_DIR or setup --data-dir "
            "to select an explicit external folder. Existing preferences were preserved."
        ) from None


def default_data_dir() -> Path:
    saved = read_location()
    if saved is not None:
        return saved.data_dir
    if LEGACY_DATA_DIR.is_absolute() and LEGACY_DATA_DIR.is_dir():
        return DataLocation(data_dir=LEGACY_DATA_DIR).data_dir
    return DataLocation(data_dir=user_dir() / "data").data_dir


def remember_location(data_dir: Path) -> Path:
    """Atomically replace only Plumb's admitted preference after a recorded success."""
    location = DataLocation(data_dir=data_dir)
    previous = read_location()  # refuse to overwrite malformed/unrelated existing content
    path = location_file()
    if previous == location:
        return path
    content = location.model_dump_json(indent=2) + "\n"
    if len(content.encode("utf-8")) > LIMIT:
        raise ValueError("Data location is too long to remember; preferences were preserved")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=".plumb-location-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "var"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    printer_enabled: bool = False

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'tandir.db').as_posix()}"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def photo_dir(self) -> Path:
        return self.storage_dir / "cake_photos"

    @property
    def avatar_dir(self) -> Path:
        return self.storage_dir / "avatars"


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("TANDIR_DATA_DIR", DEFAULT_DATA_DIR)),
        printer_enabled=os.environ.get("TANDIR_PRINTER", "off") == "on",
    )

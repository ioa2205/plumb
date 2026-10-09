from pathlib import Path

import pytest
from pydantic import ValidationError

from backend import user_config
from backend.settings import Settings

ENV = "PLUMB_DATA_DIR"


@pytest.fixture(autouse=True)
def isolated_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_config, "user_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(user_config, "LEGACY_DATA_DIR", tmp_path / "legacy")


def test_reuses_existing_legacy_data_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    user_config.LEGACY_DATA_DIR.mkdir()
    assert Settings().data_dir == user_config.LEGACY_DATA_DIR


def test_new_install_defaults_to_user_data_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert Settings().data_dir == user_config.user_dir() / "data"
    assert not user_config.user_dir().exists()


def test_empty_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "")
    assert Settings().data_dir == user_config.user_dir() / "data"


def test_environment_overrides_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV, str(tmp_path))
    assert Settings().data_dir == tmp_path


@pytest.mark.parametrize(
    "value",
    [
        "plumb-data",  # relative to the working directory
        r".\plumb-data",
        "D:plumb-data",  # drive-relative on Windows
        r"\plumb-data",  # root of the current drive, no drive letter
    ],
)
def test_rejects_paths_that_are_not_absolute(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ENV, value)
    with pytest.raises(ValidationError, match="must be an absolute path"):
        Settings()


def test_data_subdirectories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV, str(tmp_path))
    settings = Settings()
    assert settings.models_dir == tmp_path / "models"
    assert settings.llama_cpp_dir == tmp_path / "llama.cpp"
    assert settings.cache_dir == tmp_path / "cache"


def test_loading_settings_creates_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "not-yet"
    monkeypatch.setenv(ENV, str(missing))
    assert Settings().data_dir == missing
    assert not missing.exists()


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.data_dir = Path(r"C:\elsewhere")  # type: ignore[misc]


def test_port_defaults_and_stays_out_of_the_privileged_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLUMB_PORT", raising=False)
    assert Settings().port == 8700
    monkeypatch.setenv("PLUMB_PORT", "8790")
    assert Settings().port == 8790
    for value in ("0", "80", "1023", "65536", "http"):
        monkeypatch.setenv("PLUMB_PORT", value)
        with pytest.raises(ValidationError):
            Settings()


def test_the_bind_address_is_not_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_HOST", "0.0.0.0")  # noqa: S104 - must be ignored
    assert not hasattr(Settings(), "host")

"""Remember only an external data location; preserve existing content on refusal."""

import json
from pathlib import Path

import pytest

from backend import cli, serve, user_config
from backend.settings import Settings
from backend.setup import __main__ as wizard

REAL_USER_DIR = user_config.user_dir


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_config, "user_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(user_config, "LEGACY_DATA_DIR", tmp_path / "legacy")
    monkeypatch.delenv("PLUMB_DATA_DIR", raising=False)


def test_preferences_are_reused_and_argument_environment_precedence_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = tmp_path / "saved"
    user_config.LEGACY_DATA_DIR.mkdir()
    preferences = user_config.remember_location(saved)
    assert json.loads(preferences.read_text()) == {"version": 1, "data_dir": str(saved)}
    assert Settings().data_dir == saved
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "environment"))
    assert Settings().data_dir == tmp_path / "environment"
    assert Settings(data_dir=tmp_path / "explicit").data_dir == tmp_path / "explicit"
    assert not saved.exists()  # remembering storage does not start setup/inference


@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b'{"version":2,"data_dir":"relative"}',
        b'{"version":1,"data_dir":"relative"}',
        b"x" * 4097,
        b'{"version":1,"data_dir":"relative","api_key":"private fixture"}',
    ],
)
def test_invalid_preferences_refuse_without_overwriting_or_exposing_values(
    tmp_path: Path,
    content: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = user_config.location_file()
    path.parent.mkdir()
    path.write_bytes(content)
    with pytest.raises(ValueError):
        Settings()
    with pytest.raises(ValueError):
        user_config.remember_location(tmp_path / "new")
    for command in (["doctor"], ["web", "--no-open"]):
        assert cli.main(command) == 1
    assert wizard.main(["--json"]) == 1
    output = capsys.readouterr().out
    assert "private fixture" not in output and "Traceback" not in output
    assert path.read_bytes() == content
    assert not list(path.parent.glob(".plumb-location-*"))
    # An explicit override can still run diagnostics without reading bad preferences.
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "environment"))
    assert Settings().data_dir == tmp_path / "environment"


def test_preferences_cannot_point_into_the_installation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        user_config.remember_location(user_config.ROOT / "tmp/disallowed")
    assert not user_config.location_file().exists()


def test_extra_fields_with_absolute_location_are_refused(tmp_path: Path) -> None:
    path = user_config.location_file()
    path.parent.mkdir()
    path.write_text(json.dumps({"version": 1, "data_dir": str(tmp_path), "model": "unmeasured"}))
    with pytest.raises(ValueError, match="Invalid"):
        user_config.read_location()


def test_atomic_write_failure_preserves_previous_preferences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = user_config.remember_location(tmp_path / "first")
    previous = path.read_bytes()

    def refused(self: Path, target: Path) -> Path:
        raise PermissionError("fixture write refused")

    monkeypatch.setattr(Path, "replace", refused)
    with pytest.raises(PermissionError):
        user_config.remember_location(tmp_path / "second")
    assert path.read_bytes() == previous
    assert not list(path.parent.glob(".plumb-location-*"))


def test_user_directory_override_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "relative")
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    # Use the original function: the fixture isolates it for other tests.
    with pytest.raises(ValueError, match="absolute"):
        REAL_USER_DIR()


def test_symbolic_link_preferences_are_refused_before_read_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = user_config.location_file()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == path or original(self))
    with pytest.raises(ValueError, match="symbolic link"):
        user_config.remember_location(tmp_path / "new")
    assert not path.parent.exists()


def test_failed_settings_never_binds_a_web_server(monkeypatch: pytest.MonkeyPatch) -> None:
    def invalid() -> Settings:
        raise ValueError("private fixture")

    def forbidden(port: int) -> None:
        pytest.fail("Invalid settings reached the server")

    monkeypatch.setattr(serve, "Settings", invalid)
    monkeypatch.setattr(serve, "bind", forbidden)
    assert serve.main() == 1

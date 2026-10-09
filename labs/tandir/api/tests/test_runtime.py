"""How the lab is started: loopback only, seeded once."""

import pytest

import tandir.__main__ as entry
from tandir.config import Settings
from tandir.main import create_app
from tandir.seed import seed


def test_server_binds_loopback_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("TANDIR_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setattr("sys.argv", ["tandir", "--port", "8799"])
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: calls.append(kw))
    entry.main()
    assert calls == [{"host": "127.0.0.1", "port": 8799, "log_level": "info"}]


def test_there_is_no_host_option(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("TANDIR_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setattr("sys.argv", ["tandir", "--host", "0.0.0.0"])
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: calls.append(kw))
    with pytest.raises(SystemExit):
        entry.main()
    assert calls == []


def test_seed_only_seeds_and_does_not_serve(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("TANDIR_DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setattr("sys.argv", ["tandir", "--seed-only"])
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: calls.append(kw))
    entry.main()
    assert calls == []
    assert (tmp_path / "var" / "tandir.db").is_file()
    assert (tmp_path / "var" / "storage" / "avatars" / "alice.png").is_file()


def test_seeding_twice_changes_nothing(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "var")
    app = create_app(settings)
    with app.state.sessionmaker() as db:
        seed(db, settings)
        seed(db, settings)
    from sqlalchemy import func, select

    from tandir.models import Order, User

    with app.state.sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 6
        assert db.scalar(select(func.count()).select_from(Order)) == 2
    app.state.engine.dispose()


def test_printer_is_off_unless_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from tandir.config import load_settings

    monkeypatch.delenv("TANDIR_PRINTER", raising=False)
    assert load_settings().printer_enabled is False
    monkeypatch.setenv("TANDIR_PRINTER", "yes")
    assert load_settings().printer_enabled is False
    monkeypatch.setenv("TANDIR_PRINTER", "on")
    assert load_settings().printer_enabled is True

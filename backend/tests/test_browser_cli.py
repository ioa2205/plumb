"""The public and portable browser setup uses the same pinned, explicit installer."""

import pytest

from backend import cli
from backend.setup import browser


@pytest.mark.parametrize(
    "arguments,action", [([], "status"), (["check"], "check"), (["install"], "install")]
)
def test_public_browser_entry_preserves_explicit_install_and_setup_result(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], action: str
) -> None:
    calls = []

    def execute(argv: list[str]) -> int:
        calls.append(argv)
        return 1

    monkeypatch.setattr(browser, "main", execute)
    assert cli.main(["browser", *arguments]) == 1
    assert calls == [[action]]

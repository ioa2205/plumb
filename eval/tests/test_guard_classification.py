"""The development runner reads bounded source, with expectations kept out of prompts."""

import pytest

from agent.questions import guard_summary
from eval.feasibility.guard_classification import CASES, ROOT, packet_for


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_development_packets_preserve_actual_source_locations(
    case: tuple[str, tuple[tuple[str, str], ...], set[str]],
) -> None:
    _, parts, _ = case
    packet = packet_for(parts)
    assert 0 < len(packet.line_ids) <= 80
    assert {excerpt.path for excerpt in packet.excerpts} == {path for path, _ in parts}
    for excerpt in packet.excerpts:
        source = (ROOT / excerpt.path).read_text(encoding="utf-8").splitlines()
        for line in excerpt.lines:
            assert line.text.strip() in source[line.number - 1]
            assert packet.location(line.id) == (excerpt.path, line.number)
    request = guard_summary(packet).request().body()
    assert "expected" not in request["messages"][-1]["content"]


def test_missing_symbol_refuses_instead_of_sending_the_whole_file() -> None:
    with pytest.raises(LookupError):
        packet_for((("api/tandir/security.py", "absent_function"),))

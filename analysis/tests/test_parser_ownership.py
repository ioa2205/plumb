"""Native parser state must not cross worker threads; parsed source is never executed."""

import gc
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from analysis.syntax import _parser, code_only, comparisons, extract
from backend.contracts.common import Language


def test_mutable_parsers_are_reused_only_within_their_thread() -> None:
    barrier = Barrier(3)

    def owner() -> object:
        parser = _parser(Language.PYTHON)
        assert parser is _parser(Language.PYTHON)
        barrier.wait(timeout=10)
        return parser

    with ThreadPoolExecutor(max_workers=3) as executor:
        owned = list(executor.map(lambda _: owner(), range(3)))
    assert len({id(parser) for parser in owned}) == 3
    assert all(parser is not _parser(Language.PYTHON) for parser in owned)


def test_worker_churn_gc_and_mixed_grammars_preserve_exact_evidence() -> None:
    python = (
        b'def check(order, user):\n    """not proof"""\n'
        b"    # reviewed: safe\n    return order.owner == user.id\n"
    )
    typescript = (
        b"// reviewed: safe\n"
        b"export function check(order, user) { return order.owner === user.id; }\n"
    )

    def read(language: Language, source: bytes) -> None:
        clean = code_only(language, source)
        gc.collect()
        assert b"reviewed" not in clean and len(clean) == len(source)
        found = comparisons(language, source)
        assert len(found) == 1 and found[0].operands == ("order.owner", "user.id")
        facts = extract(
            "fixture.py" if language is Language.PYTHON else "fixture.ts", language, source, set()
        )
        assert any(symbol.name == "check" for symbol in facts.symbols) and not facts.has_errors

    for _ in range(12):
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(read, language, source)
                for language, source in (
                    (Language.PYTHON, python),
                    (Language.TYPESCRIPT, typescript),
                    (Language.TSX, typescript),
                )
            ]
            for future in futures:
                future.result(timeout=10)

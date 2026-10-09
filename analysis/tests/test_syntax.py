from analysis.syntax import code_only, comparisons, remarks
from backend.contracts.common import Language


def spans(language: Language, source: str) -> list[str]:
    data = source.encode()
    return [data[start:end].decode() for start, end in remarks(language, data)]


def test_python_remarks_are_comments_and_string_statements() -> None:
    source = (
        '"""Module docstring."""\n'
        "import os  # trailing\n"
        "\n"
        "def load(order_id):\n"
        "    '''Docstring\n"
        "    over two lines.'''\n"
        '    "a bare string does nothing"\n'
        '    url = "http://example.test/#fragment"\n'
        '    return f"{order_id}"  # the id\n'
    )
    assert spans(Language.PYTHON, source) == [
        '"""Module docstring."""',
        "# trailing",
        "'''Docstring\n    over two lines.'''",
        '"a bare string does nothing"',
        "# the id",
    ]


def test_python_strings_that_are_used_are_not_remarks() -> None:
    source = 'x = "value"\nprint("""text""")\nraise ValueError("# not a comment")\n'
    assert spans(Language.PYTHON, source) == []


def test_typescript_remarks_are_comments_and_never_directives() -> None:
    source = (
        '"use server";\n'
        "// line\n"
        "export async function act() {\n"
        '  "use server";\n'
        "  /* block\n"
        "     comment */\n"
        '  return "// text";\n'
        "}\n"
    )
    for language in (Language.TYPESCRIPT, Language.TSX):
        assert spans(language, source) == ["// line", "/* block\n     comment */"]


def test_jsx_comments_are_remarks() -> None:
    source = "export const A = () => <p>{/* hidden */}text // shown</p>;\n"
    assert spans(Language.TSX, source) == ["/* hidden */"]


def test_remarks_are_found_in_code_that_does_not_parse() -> None:
    source = "def broken(:\n    # still a comment\n    return\n"
    assert spans(Language.PYTHON, source) == ["# still a comment"]


def test_code_only_blanks_remarks_and_keeps_every_offset() -> None:
    source = b'x = 1  # one\n"""doc\nstring"""\ny = 2\n'
    code = code_only(Language.PYTHON, source)
    assert len(code) == len(source)
    assert code.decode().split("\n") == ["x = 1  " + " " * 5, " " * 6, " " * 9, "y = 2", ""]
    # No comment syntax is known for other files, so nothing is blanked.
    assert code_only(None, source) == source


def test_python_comparisons_are_single_equality_or_membership_tests() -> None:
    source = (
        b"if order is None or order.customer_id != user.id:\n"
        b"    pass\n"
        b"ok = a < b < c or x <= y\n"
        b"allowed = user.role in ('admin', 'manager')\n"
        b"statement = select(Order).where(Order.customer_id == user.id)\n"
    )
    found = comparisons(Language.PYTHON, source)
    assert [(c.start_line, c.end_line, c.operator, c.operands) for c in found] == [
        (1, 1, "!=", ("order.customer_id", "user.id")),
        (4, 4, "in", ("user.role", "('admin', 'manager')")),
        (5, 5, "==", ("Order.customer_id", "user.id")),
    ]


def test_typescript_comparisons_are_equality_tests() -> None:
    source = (
        b"if (!order || order.customerId !== viewer.id) return null;\n"
        b'const other = a > b && "x" in obj;\n'
        b'if (viewer.role == "admin") {}\n'
    )
    for language in (Language.TYPESCRIPT, Language.TSX):
        found = comparisons(language, source)
        assert [(c.start_line, c.operator, c.operands) for c in found] == [
            (1, "!==", ("order.customerId", "viewer.id")),
            (3, "==", ("viewer.role", '"admin"')),
        ]

import re
from collections import Counter

import libcst as cst
import pytest

from backend.contracts.common import Family
from eval.mutation.corpus import ORIGINAL, Variant, build, handler_lines, normalize
from eval.mutation.operators import OPERATORS
from eval.mutation.templates import Template, load_templates

TEMPLATES = load_templates()
AUTHZ = [t for t in TEMPLATES if t.family is Family.AUTHORIZATION]
INJECTION = [t for t in TEMPLATES if t.family is Family.INJECTION]
CORPUS = build(TEMPLATES)
BY_ID = {v.id: v for v in CORPUS}


def variant(template: Template, operator: str) -> Variant:
    return BY_ID[f"{template.name}/{operator}"]


def owner_check(t: Template) -> str:
    return f"{t.var}.{t.owner_field} != {t.principal}.id"


def handler_source(v: Variant) -> str:
    start, end = v.handler_lines
    return "\n".join(v.source.splitlines()[start - 1 : end])


# --- the corpus as a whole -----------------------------------------------------------------------


def test_every_operator_applies_to_every_template_of_its_family() -> None:
    counts = Counter(v.operator for v in CORPUS)
    assert counts[ORIGINAL] == len(TEMPLATES)
    assert len(AUTHZ) >= 20 and len(INJECTION) >= 10  # task M1.6a
    for op in OPERATORS:
        expected = len(AUTHZ) if op.family is Family.AUTHORIZATION else len(INJECTION)
        assert counts[op.name] == expected, op.name
    assert len(CORPUS) == len(TEMPLATES) + 4 * len(AUTHZ) + 2 * len(INJECTION)


def test_labels_follow_the_operator_and_originals_are_safe() -> None:
    labels = Counter((v.operator, v.label) for v in CORPUS)
    assert labels[(ORIGINAL, "safe")] == len(TEMPLATES)
    for op in OPERATORS:
        assert all(v.label == op.label for v in CORPUS if v.operator == op.name)


def test_variants_parse_are_unique_and_deterministic() -> None:
    assert len(BY_ID) == len(CORPUS)
    assert len({v.sha256 for v in CORPUS}) == len(CORPUS), "two variants have identical source"
    for v in CORPUS:
        cst.parse_module(v.source)
    again = build(TEMPLATES)
    assert [v.sha256 for v in again] == [v.sha256 for v in CORPUS]


def test_every_variant_is_formatted_the_same_way() -> None:
    for v in CORPUS:
        assert normalize(v.source) == v.source, v.id
        assert max(len(line) for line in v.source.splitlines()) <= 100, v.id


def test_handler_lines_cover_the_decorated_handler() -> None:
    for v in CORPUS:
        start, end = v.handler_lines
        lines = v.source.splitlines()
        assert lines[start - 1].startswith("@router."), v.id
        assert f"def {v.handler}(" in lines[start]
        assert 1 <= start < end <= len(lines)
    with pytest.raises(LookupError):
        handler_lines("x = 1\n", "missing")


def test_operators_do_not_apply_across_families() -> None:
    for op in OPERATORS:
        others = INJECTION if op.family is Family.AUTHORIZATION else AUTHZ
        assert all(op.apply(t) is None for t in others), op.name


def test_templates_and_variants_carry_no_comments() -> None:
    # Comments would be a label tell; the adversarial slice adds them on purpose later.
    for v in CORPUS:
        assert "#" not in v.source, v.id


# --- authorization operators ---------------------------------------------------------------------


@pytest.mark.parametrize("t", AUTHZ, ids=lambda t: t.name)
def test_drop_owner_check_removes_only_the_owner_comparison(t: Template) -> None:
    original, mutated = variant(t, ORIGINAL), variant(t, "drop_owner_check")
    assert owner_check(t) in original.source
    assert owner_check(t) not in mutated.source
    assert f"{t.var} = db.get({t.model}, {t.id_param})" in mutated.source
    assert f"if {t.var} is None" in mutated.source  # the existence check stays


@pytest.mark.parametrize("t", AUTHZ, ids=lambda t: t.name)
def test_wrong_field_compares_the_caller_with_another_field(t: Template) -> None:
    mutated = variant(t, "wrong_field").source
    assert owner_check(t) not in mutated
    assert f"{t.var}.{t.wrong_field} != {t.principal}.id" in mutated


@pytest.mark.parametrize("t", AUTHZ, ids=lambda t: t.name)
def test_query_scope_moves_ownership_into_the_query(t: Template) -> None:
    source = variant(t, "query_scope_equivalent").source
    compact = re.sub(r"\s+", " ", source)
    assert f"db.get({t.model}" not in source
    assert owner_check(t) not in source
    assert f"{t.model}.{t.owner_field} == {t.principal}.id" in compact
    assert f"select({t.model}).where( {t.model}.id == {t.id_param}" in compact or (
        f"select({t.model}).where({t.model}.id == {t.id_param}" in compact
    )
    assert "from sqlalchemy import select" in source
    assert f"if {t.var} is None" in source


@pytest.mark.parametrize("t", AUTHZ, ids=lambda t: t.name)
def test_move_to_dependency_keeps_the_check_in_the_dependency(t: Template) -> None:
    v = variant(t, "move_to_dependency")
    module = cst.parse_module(v.source)
    functions = {f.name.value: f for f in module.body if isinstance(f, cst.FunctionDef)}
    dependency = cst.Module([]).code_for_node(functions[f"owned_{t.var}"])
    handler = handler_source(v)
    assert owner_check(t) in dependency
    assert f"return {t.var}" in dependency
    assert f"{t.var}: {t.model} = Depends(owned_{t.var})" in handler
    assert "db.get(" not in handler
    assert f"{t.id_param}: int" not in handler


# --- injection operators -----------------------------------------------------------------------


@pytest.mark.parametrize("t", INJECTION, ids=lambda t: t.name)
def test_sql_fstring_inlines_the_request_value(t: Template) -> None:
    source = variant(t, "sql_fstring").source
    assert re.search(r'text\(\s*(?:"[^"]*"\s*)*f"', source), "the SQL text is an f-string"
    assert f":{t.param}" not in source
    assert f'"{t.param}":' not in source  # the bound value is gone from the parameters
    assert re.search(r"'[^']*\{" + re.escape(t.param or "") + r"\}[^']*'", source)


@pytest.mark.parametrize("t", INJECTION, ids=lambda t: t.name)
def test_bound_parameters_keep_every_value_bound(t: Template) -> None:
    source = variant(t, "bound_parameters").source
    assert ".bindparams(" in source
    assert f":{t.param}" in source
    assert 'text(f"' not in source
    assert f"{t.param}=" in source


def test_order_status_filter_keeps_the_trusted_parameter_bound() -> None:
    # Only the request-controlled value is inlined; the branch scope stays a bound parameter.
    t = next(t for t in INJECTION if t.name == "order_status_filter")
    source = variant(t, "sql_fstring").source
    assert ":branch" in source
    assert '{"branch": user.branch_id}' in source

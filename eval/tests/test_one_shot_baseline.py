from jsonschema import Draft202012Validator

from backend.contracts.common import Family
from eval.baselines.common import case_path
from eval.baselines.one_shot import SYSTEM, numbered, schema, to_predictions
from eval.mutation.corpus import build

CASE = next(v for v in build() if v.id == "order_receipt/drop_owner_check")


def test_the_model_sees_numbered_source_and_nothing_that_names_the_label() -> None:
    text = numbered(CASE.source)
    lines = text.splitlines()
    assert lines[0].startswith("  1 | from fastapi")
    assert len(lines) == len(CASE.source.splitlines())
    for word in ("drop_owner_check", "vulnerable", "original", "order_receipt"):
        assert word not in text
    for word in ("drop_owner_check", "order_receipt", "original"):
        assert word not in SYSTEM


def test_schema_bounds_line_numbers_to_the_file() -> None:
    validator = Draft202012Validator(schema(20))
    finding = {"family": "authorization", "start_line": 18, "end_line": 19, "explanation": "x"}
    assert list(validator.iter_errors({"findings": [finding]})) == []
    assert list(validator.iter_errors({"findings": []})) == []
    assert list(validator.iter_errors({"findings": [{**finding, "end_line": 21}]}))
    assert list(validator.iter_errors({"findings": [{**finding, "family": "xss"}]}))


def test_answers_become_predictions_with_ordered_lines() -> None:
    answer = {
        "findings": [
            {"family": "authorization", "start_line": 19, "end_line": 17, "explanation": "x"}
        ]
    }
    [p] = to_predictions(CASE, answer)
    assert (p.family, p.path, p.start_line, p.end_line) == (
        Family.AUTHORIZATION,
        case_path(CASE),
        17,
        19,
    )
    assert to_predictions(CASE, {"findings": []}) == []

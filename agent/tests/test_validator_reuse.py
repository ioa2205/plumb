"""Reuse cannot confer authority on changed claims, mutable outputs or another snapshot."""

import pytest

from agent.tests.test_validator import ORDERS_PY, Lab
from agent.tests.test_validator import lab as lab
from agent.validator import Unconfirmed, Validator


def test_cached_guard_outputs_are_independent_and_changed_claims_are_revalidated(lab: Lab) -> None:
    validator = Validator(lab.snapshot, lab.store)
    guard = lab.guard(lab.span(ORDERS_PY, 16, 21))
    first = validator.confirm(guard, subject="user.id", object="order.customer_id")
    # Deliberately bypass the frozen contract, as model_copy callers can do too.
    object.__setattr__(first.span, "content_sha256", "0" * 64)
    object.__setattr__(first, "confirmed", False)
    second = validator.confirm(guard, subject="user.id", object="order.customer_id")
    assert second.confirmed and second.span.content_sha256 != "0" * 64
    with pytest.raises(Unconfirmed):
        validator.confirm(guard, subject="attacker.id", object="order.customer_id")
    bad = guard.model_copy(
        update={"span": guard.span.model_copy(update={"content_sha256": "0" * 64})}
    )
    with pytest.raises(Unconfirmed):
        validator.confirm(bad, subject="user.id", object="order.customer_id")
    bad = guard.model_copy(update={"span": guard.span.model_copy(update={"snapshot_id": "0" * 64})})
    with pytest.raises(Unconfirmed):
        validator.confirm(bad, subject="user.id", object="order.customer_id")


def test_code_reuse_still_rejects_bad_hashes_and_comment_only_citations(lab: Lab) -> None:
    validator = Validator(lab.snapshot, lab.store)
    code = lab.span(ORDERS_PY, 16, 21)
    assert not validator.evidence(code)
    # A comment in the same cached file cannot inherit the code citation's authority.
    comment = lab.span(ORDERS_PY, 8, 8)
    assert validator.evidence(comment)
    changed = code.model_copy(update={"content_sha256": "0" * 64})
    assert validator.evidence(changed)

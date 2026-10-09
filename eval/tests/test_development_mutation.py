"""Construction and split boundaries; no generated fixture is ever executed."""

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.contracts.common import Family
from eval.mutation import development as dev
from eval.mutation.corpus import normalize
from eval.mutation.extended_fixtures import FIXTURES, Rewrite
from eval.mutation.extended_operators import EXTRA_OWNER_OPERATORS
from eval.mutation.templates import TEMPLATE_DIR


@pytest.fixture(scope="module")
def cases() -> list[dev.Case]:
    return dev.make_cases()


def one(cases: list[dev.Case], operator: str, template: str = "order_receipt") -> dev.Case:
    return next(c for c in cases if c.template == template and c.operator == operator)


def fn(case: dev.Case) -> ast.FunctionDef:
    tree = ast.parse(case.sources["api/input.py"])
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == case.entry)


def owner_comparisons(function: ast.AST, field: str = "customer_id") -> list[ast.Compare]:
    return [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Attribute) and n.left.attr == field
    ]


def test_all_declared_kinds_have_exact_controls_and_known_construction_labels(
    cases: list[dev.Case],
) -> None:
    by_id = {c.id: c for c in cases}
    assert {c.operator for c in cases} - {"original"} == dev.REQUIRED
    assert len(by_id) == len(cases)
    assert {c.family for c in cases} == set(Family)
    assert all(by_id[c.control_id].label == "safe" for c in cases)
    assert all(by_id[c.control_id].template == c.template for c in cases)
    assert all(
        c.input_sha256 == hashlib.sha256(dev.canonical(c.sources)).hexdigest() for c in cases
    )
    assert len({c.input_sha256 for c in cases}) == len(cases)


def test_new_generator_never_reads_a_legacy_validation_or_test_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = json.loads(dev.LEGACY_MANIFEST.read_bytes())
    original = Path.read_text
    read = []

    def guarded(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.parent == TEMPLATE_DIR and path.suffix == ".py":
            assert frozen["templates"][path.stem] == "development"
            read.append(path.stem)
        return original(path, encoding=encoding, errors=errors)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("development extension opened the legacy split loader")

    monkeypatch.setattr(Path, "read_text", guarded)
    monkeypatch.setattr("eval.splits.load", forbidden)
    assert dev.make_cases()
    assert set(read) == {
        name for name, split in frozen["templates"].items() if split == "development"
    }


def test_existing_variant_hashes_memberships_and_legacy_seal_are_retained(
    cases: list[dev.Case],
) -> None:
    frozen = json.loads(dev.LEGACY_MANIFEST.read_bytes())
    existing = frozen["splits"]["development"]
    actual = {
        c.id: hashlib.sha256(c.sources["api/input.py"].encode()).hexdigest()
        for c in cases
        if c.id in existing
    }
    assert actual == existing
    new_clusters = {c.template for c in cases} - set(frozen["templates"])
    assert new_clusters and all(name.startswith("v2_") for name in new_clusters)
    assert not {c.template for c in cases} & {
        name for name, s in frozen["templates"].items() if s != "development"
    }
    manifest: Any = dev.manifest_for(cases)
    assert (
        manifest["base_manifest_sha256"]
        == hashlib.sha256(dev.LEGACY_MANIFEST.read_bytes()).hexdigest()
    )
    assert manifest["scope"] == "development_only" and manifest["final_candidate"] is False
    assert all(record["split"] == "development" for record in manifest["cases"])


def test_client_identity_is_bound_to_a_request_parameter_not_the_session(
    cases: list[dev.Case],
) -> None:
    function = fn(one(cases, "client_user_id"))
    assert "requested_owner" in [arg.arg for arg in function.args.args]
    comparisons = owner_comparisons(function)
    assert len(comparisons) == 1
    assert ast.unparse(comparisons[0].comparators[0]) == "requested_owner"


def test_after_return_and_dead_branch_cannot_enforce_the_denial(cases: list[dev.Case]) -> None:
    late = fn(one(cases, "check_after_return"))
    returned_at = next(i for i, node in enumerate(late.body) if isinstance(node, ast.Return))
    guarded_at = next(
        i
        for i, node in enumerate(late.body)
        if isinstance(node, ast.If) and owner_comparisons(node)
    )
    assert guarded_at > returned_at
    dead = fn(one(cases, "dead_guard"))
    branches = [
        n
        for n in dead.body
        if isinstance(n, ast.If) and isinstance(n.test, ast.Constant) and n.test.value is False
    ]
    assert len(branches) == 1 and any(isinstance(n, ast.Raise) for n in ast.walk(branches[0]))


def test_discarded_and_lying_helpers_do_not_dominate_the_handler(cases: list[dev.Case]) -> None:
    for operator, helper in (
        ("discarded_guard_result", "is_owner"),
        ("lying_helper_name", "require_owner"),
    ):
        case = one(cases, operator)
        function = fn(case)
        assert not owner_comparisons(function)
        call = next(
            n for n in function.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        )
        assert isinstance(call.value, ast.Call)
        assert isinstance(call.value.func, ast.Name) and call.value.func.id == helper
        definition = next(
            n
            for n in ast.parse(case.sources["api/input.py"]).body
            if isinstance(n, ast.FunctionDef) and n.name == helper
        )
        returned = next(n for n in definition.body if isinstance(n, ast.Return))
        if operator == "lying_helper_name":
            assert isinstance(returned.value, ast.Constant) and returned.value.value is True
        else:
            assert isinstance(returned.value, ast.Compare)


def test_renamed_and_decorated_guards_keep_actual_enforcement(cases: list[dev.Case]) -> None:
    renamed = one(cases, "rename_helper")
    function = fn(renamed)
    guard = next(
        n for n in function.body if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
    )
    assert isinstance(guard.test, ast.UnaryOp)
    assert isinstance(guard.test.operand, ast.Call) and any(
        isinstance(n, ast.Raise) for n in guard.body
    )
    assert "record.customer_id == principal.id" in renamed.sources["api/input.py"]
    decorated = one(cases, "guard_decorator")
    function = fn(decorated)
    assert ast.unparse(function.decorator_list[-1]) == "enforce_owner"
    assert not owner_comparisons(function)
    tree = ast.parse(decorated.sources["api/input.py"])
    wrapper = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "wrapped"
    )
    assert any(isinstance(n, ast.Raise) for n in ast.walk(wrapper))
    assert "record.customer_id != values['user'].id" in ast.unparse(wrapper)
    assert "signature(handler).bind(*args, **kwargs)" in ast.unparse(wrapper)


def test_decoy_query_is_a_different_record_and_tenant_denial_really_disappears(
    cases: list[dev.Case],
) -> None:
    decoy = fn(one(cases, "decoy_guard"))
    comparisons = owner_comparisons(decoy)
    assert comparisons and all(ast.unparse(c.left) == "decoy.customer_id" for c in comparisons)
    assert "db.get(Order, 0)" in ast.unparse(decoy)
    role = one(cases, "role_without_tenant", "v2_tenant_role").sources["api/role.py"]
    assert 'user.role != "manager"' in role and "tenant_id" not in role
    assert "tenant_id" in one(cases, "original", "v2_tenant_role").sources["api/role.py"]


def test_identifier_command_and_path_pairs_keep_their_security_boundaries(
    cases: list[dev.Case],
) -> None:
    unsafe = one(cases, "order_by_input", "v2_identifier_order").sources["api/sort.py"]
    safe = one(cases, "allowlisted_identifiers", "v2_identifier_order").sources["api/sort.py"]
    assert "column = sort" in unsafe and ":status" in unsafe
    assert 'if sort == "date"' in safe and 'column = "created_at"' in safe
    assert 'elif sort == "amount"' in safe and "raise HTTPException" in safe
    shell = ast.parse(one(cases, "shell_input", "v2_command_arguments").sources["api/command.py"])
    call = next(
        n
        for n in ast.walk(shell)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run"
    )
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "text"
    shell_value = next(k.value for k in call.keywords if k.arg == "shell")
    assert isinstance(shell_value, ast.Constant) and shell_value.value is True
    array = one(cases, "argument_arrays", "v2_command_arguments").sources["api/command.py"]
    assert 'arguments = ["preview-tool", "--", text]' in array and "shell=False" in array
    raw = one(cases, "unchecked_path_join", "v2_path_containment").sources["api/path.py"]
    contained = one(cases, "resolve_and_contain", "v2_path_containment").sources["api/path.py"]
    assert "path = ROOT / name" in raw and "path.is_relative_to" not in raw
    assert "path = (ROOT / name).resolve()" in contained and "ROOT not in path.parents" in contained


def test_nextjs_actions_proxy_dal_and_projection_pairs_are_real_code_changes(
    cases: list[dev.Case],
) -> None:
    action = one(cases, "action_without_authorization", "v2_action_policy")
    assert "ownerId !== user.id" not in action.sources["app/orders/actions.ts"]
    proxy = one(cases, "proxy_only_protection", "v2_proxy_only")
    assert "ownerId !== user.id" not in proxy.sources["app/orders/actions.ts"]
    assert "ownerId !== user.id" in proxy.sources["proxy.ts"]
    dal = one(cases, "dal_check", "v2_action_policy").sources["app/orders/actions.ts"]
    assert "await loadOwnedOrder(orderId, user.id)" in dal
    assert "order.ownerId !== userId" in dal and "throw new Error" in dal
    wide = one(cases, "over_shared_props", "v2_client_projection")
    dto = one(cases, "dto_projection", "v2_client_projection")
    assert wide.allowed_client_fields == ("id", "amount")
    assert "record={record}" in wide.sources["app/orders/page.tsx"]
    assert (
        "const dto = { id: record.id, amount: record.amount }" in dto.sources["app/orders/page.tsx"]
    )
    assert '"use client"' in dto.sources["app/orders/Details.tsx"]


def test_adversarial_text_never_changes_ground_truth_or_parent_inputs(
    cases: list[dev.Case],
) -> None:
    by_id = {c.id: c for c in cases}
    for case in cases:
        if case.adversarial_parent is None:
            continue
        parent = by_id[case.adversarial_parent]
        assert (case.label, case.control_id, case.family) == (
            parent.label,
            parent.control_id,
            parent.family,
        )
        assert case.input_sha256 != parent.input_sha256
        if case.operator == "reviewer_readme":
            assert {p: s for p, s in case.sources.items() if p != "README.md"} == parent.sources
        else:
            assert sum(case.sources[p] != s for p, s in parent.sources.items()) == 1
    assert {c.label for c in cases if c.adversarial_parent} == {"safe", "vulnerable"}


def test_preconditions_refuse_wrong_family_absent_guard_and_ambiguous_rewrite() -> None:
    template = dev.development_templates()[0]
    for op in EXTRA_OWNER_OPERATORS:
        assert op.apply(template.model_copy(update={"family": Family.PATH_TRAVERSAL})) is None
        assert (
            op.apply(
                template.model_copy(
                    update={
                        "source": template.source.replace(
                            f"{template.var}.{template.owner_field}", "unrelated.field"
                        )
                    }
                )
            )
            is None
        )
    rewrite = FIXTURES[0].rewrites[0]
    assert rewrite.apply({}) is None
    assert rewrite.apply({rewrite.path: rewrite.before * 2}) is None
    assert Rewrite("same", "safe", "x.py", "x", "x", 1).apply({"x.py": "x"}) is None


def test_manifest_is_current_metadata_only_and_cli_cannot_reseal(
    tmp_path: Path, cases: list[dev.Case], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real CLI consistency check, including current source generation and pins.
    assert dev.main(["check"]) == 0
    monkeypatch.setattr(dev, "make_cases", lambda: cases)
    assert dev.check() == cases
    manifest = json.loads(dev.MANIFEST.read_bytes())
    assert manifest == dev.manifest_for(cases)
    assert "source" not in manifest and "sealed_test_sha256" not in manifest
    assert all("import " not in str(row["sources"]) for row in manifest["cases"])
    target = tmp_path / "manifest.json"
    assert dev.main(["freeze", "--manifest", str(target)]) == 0
    original = target.read_bytes()
    assert dev.main(["freeze", "--manifest", str(target)]) == 1
    assert target.read_bytes() == original
    value = json.loads(original)
    value["cases"][0]["label"] = "vulnerable" if value["cases"][0]["label"] == "safe" else "safe"
    target.write_text(json.dumps(value))
    assert dev.main(["check", "--manifest", str(target)]) == 1
    with pytest.raises(SystemExit):
        dev.main(["test"])
    with pytest.raises(SystemExit):
        dev.main(["check", "--open-sealed"])


def test_canonical_format_and_input_paths_are_bounded(cases: list[dev.Case]) -> None:
    for case in cases:
        for path, text in case.sources.items():
            if path.endswith(".py"):
                assert normalize(text) == text
    base = cases[0].model_dump()
    for invalid in (
        {"../escape.py": "x = 1\n"},
        {"api/input.py": "x =\n"},
        {"api/input.py": "x = 1\r\n"},
        {"api/input.py": "x" * 100_001 + "\n"},
    ):
        with pytest.raises(ValidationError):
            dev.Case.model_validate({**base, "sources": invalid})

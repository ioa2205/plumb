"""Additional owner-guard transformations of synthetic development inputs only.

Legacy OPERATORS and the sealed corpus deliberately do not import this registry.
Generated handlers are parsed/formatted as data, never imported or executed.
"""

from typing import ClassVar, Literal

import libcst as cst
import libcst.matchers as m

from backend.contracts.common import Family
from eval.mutation.operators import (
    Label,
    _code,
    _handler,
    _is_owner_guard,
    _owner_comparison,
    _replace_handler,
    _statements,
    _strip_owner_check,
)
from eval.mutation.templates import Template

Kind = Literal[
    "client_user_id",
    "check_after_return",
    "dead_guard",
    "discarded_guard_result",
    "rename_helper",
    "guard_decorator",
    "lying_helper_name",
    "decoy_guard",
]


class OwnerMutation:
    family: ClassVar[Family] = Family.AUTHORIZATION
    cwe: ClassVar[int] = 639

    def __init__(self, name: Kind, *, safe: bool = False) -> None:
        self.name = name
        self.label: Label = "safe" if safe else "vulnerable"
        self.description = name.replace("_", " ")

    def apply(self, template: Template) -> str | None:
        if template.family is not self.family:
            return None
        module = cst.parse_module(template.source)
        changed = self.mutate(module, template)
        return changed.code if changed is not None and changed.code != module.code else None

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        t = template
        if not all((t.var, t.owner_field, t.principal, t.model, t.id_param)):
            return None
        fn = _handler(module, t.handler)
        statements = _statements(fn)
        target = _owner_comparison(t)
        guards = [i for i, stmt in enumerate(statements) if _is_owner_guard(stmt, target)]
        # Exact single mandatory denial only; don't label arbitrary unfamiliar input.
        if len(guards) != 1 or not isinstance(fn.body, cst.IndentedBlock):
            return None
        original_guard = statements[guards[0]]
        if not isinstance(original_guard, cst.If):
            return None
        comparisons = m.findall(original_guard.test, target)
        if len(comparisons) != 1 or original_guard.orelse is not None:
            return None
        if not any(isinstance(node, cst.Raise) for node in m.findall(original_guard, m.Raise())):
            return None
        body = _strip_owner_check(statements, target)
        at = len(_strip_owner_check(statements[: guards[0] + 1], target))
        comparison = f"{t.var}.{t.owner_field} != {t.principal}.id"
        denial = cst.parse_statement(
            f"if {comparison}:\n    raise HTTPException(status_code=404, detail='Not found')\n"
        )
        helpers = ""
        decorators = fn.decorators
        params = fn.params
        if self.name == "client_user_id":
            if "requested_owner" in _code(fn):
                return None
            new_guard = original_guard.visit(_ClientIdentity(t.principal or ""))
            if not isinstance(new_guard, cst.If):
                return None
            body = statements[:]
            body[guards[0]] = new_guard
            plain = [p for p in params.params if p.default is None]
            defaulted = [p for p in params.params if p.default is not None]
            params = params.with_changes(
                params=[
                    *plain,
                    cst.Param(
                        cst.Name("requested_owner"), annotation=cst.Annotation(cst.Name("int"))
                    ),
                    *defaulted,
                ]
            )
        elif self.name == "check_after_return":
            # Mutating handlers returning None still return before the moved denial.
            if not any(m.findall(stmt, m.Return()) for stmt in body):
                body.append(cst.parse_statement("return None\n"))
            body.append(denial)
        elif self.name == "dead_guard":
            body.insert(
                at,
                cst.parse_statement(
                    f"if False:\n    if {comparison}:\n"
                    "        raise HTTPException(status_code=404)\n"
                ),
            )
        elif self.name == "decoy_guard":
            body[at:at] = [
                cst.parse_statement(f"decoy = db.get({t.model}, 0)\n"),
                cst.parse_statement(
                    f"if decoy is not None and decoy.{t.owner_field} != {t.principal}.id:\n"
                    "    raise HTTPException(status_code=404)\n"
                ),
            ]
        elif self.name == "guard_decorator":
            if "enforce_owner" in module.code:
                return None
            helpers = (
                "from functools import wraps\nfrom inspect import signature\n\n"
                "def enforce_owner(handler):\n"
                "    @wraps(handler)\n"
                "    def wrapped(*args, **kwargs):\n"
                "        values = signature(handler).bind(*args, **kwargs).arguments\n"
                f"        record = values['db'].get({t.model}, values['{t.id_param}'])\n"
                f"        if record is None or record.{t.owner_field} "
                f"!= values['{t.principal}'].id:\n"
                "            raise HTTPException(status_code=404)\n"
                "        return handler(*args, **kwargs)\n"
                "    return wrapped\n\n"
            )
            # Route registration sees the protected wrapper, whose signature is preserved.
            decorators = [*decorators, cst.Decorator(cst.Name("enforce_owner"))]
        else:
            helper = (
                "belongs_to_principal"
                if self.name == "rename_helper"
                else ("require_owner" if self.name == "lying_helper_name" else "is_owner")
            )
            if helper in module.code:
                return None
            result = (
                "True"
                if self.name == "lying_helper_name"
                else f"record.{t.owner_field} == principal.id"
            )
            helpers = f"def {helper}(record, principal):\n    return {result}\n\n"
            call = f"{helper}({t.var}, {t.principal})"
            body.insert(
                at,
                cst.parse_statement(
                    f"if not {call}:\n    raise HTTPException(status_code=404)\n"
                    if self.name == "rename_helper"
                    else f"{call}\n"
                ),
            )
        changed = fn.with_changes(
            params=params, decorators=decorators, body=fn.body.with_changes(body=body)
        )
        result_module = _replace_handler(module, changed)
        if helpers:
            position = next(
                i
                for i, s in enumerate(result_module.body)
                if isinstance(s, cst.FunctionDef) and s.name.value == t.handler
            )
            result_module = result_module.with_changes(
                body=[
                    *result_module.body[:position],
                    *cst.parse_module(helpers).body,
                    *result_module.body[position:],
                ]
            )
        return result_module


class _ClientIdentity(cst.CSTTransformer):
    def __init__(self, principal: str) -> None:
        self.principal = principal

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        if (
            isinstance(original_node.value, cst.Name)
            and original_node.value.value == self.principal
            and original_node.attr.value == "id"
        ):
            return cst.Name("requested_owner")
        return updated_node


EXTRA_OWNER_OPERATORS = (
    OwnerMutation("client_user_id"),
    OwnerMutation("check_after_return"),
    OwnerMutation("dead_guard"),
    OwnerMutation("discarded_guard_result"),
    OwnerMutation("rename_helper", safe=True),
    OwnerMutation("guard_decorator", safe=True),
    OwnerMutation("lying_helper_name"),
    OwnerMutation("decoy_guard"),
)

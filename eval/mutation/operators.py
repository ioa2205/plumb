"""Mutation operators over libcst syntax trees.

Each operator rewrites one safe template into a variant whose label is known
by construction: ``vulnerable`` operators break the protection, ``safe``
operators express the same protection in a different form. An operator returns
``None`` when it does not apply to a template.
"""

import ast
import re
import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Literal

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor

from backend.contracts.common import Family
from eval.mutation.templates import Template

Label = Literal["vulnerable", "safe"]

_code = cst.Module([]).code_for_node


class Operator(ABC):
    name: ClassVar[str]
    label: ClassVar[Label]
    family: ClassVar[Family]
    cwe: ClassVar[int]
    description: ClassVar[str]

    def applies_to(self, template: Template) -> bool:
        return template.family is self.family

    def apply(self, template: Template) -> str | None:
        if not self.applies_to(template):
            return None
        module = cst.parse_module(template.source)
        mutated = self.mutate(module, template)
        if mutated is None or mutated.code == module.code:
            return None
        return mutated.code

    @abstractmethod
    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None: ...


# --- helpers -----------------------------------------------------------------------------------


def _owner_comparison(t: Template) -> m.Comparison:
    return m.Comparison(
        left=m.Attribute(value=m.Name(t.var or ""), attr=m.Name(t.owner_field or "")),
        comparisons=[
            m.ComparisonTarget(
                operator=m.NotEqual(),
                comparator=m.Attribute(value=m.Name(t.principal or ""), attr=m.Name("id")),
            )
        ],
    )


def _without(expr: cst.BaseExpression, target: m.Comparison) -> cst.BaseExpression | None:
    """``expr`` with the ``or``-operand matching ``target`` removed; None if nothing is left."""
    if m.matches(expr, target):
        return None
    if isinstance(expr, cst.BooleanOperation) and isinstance(expr.operator, cst.Or):
        left, right = _without(expr.left, target), _without(expr.right, target)
        if left is None:
            return right
        if right is None:
            return left
        return expr.with_changes(left=left, right=right)
    return expr


def _handler(module: cst.Module, name: str) -> cst.FunctionDef:
    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef) and stmt.name.value == name:
            return stmt
    raise LookupError(f"handler {name} not found")


def _statements(fn: cst.FunctionDef) -> list[cst.BaseStatement]:
    """The handler's statements; a one-line body has none we can rewrite."""
    return list(fn.body.body) if isinstance(fn.body, cst.IndentedBlock) else []


def _replace_handler(module: cst.Module, new: cst.FunctionDef) -> cst.Module:
    body = [
        new if isinstance(s, cst.FunctionDef) and s.name.value == new.name.value else s
        for s in module.body
    ]
    return module.with_changes(body=body)


def _add_import(module: cst.Module, package: str, obj: str) -> cst.Module:
    context = CodemodContext()
    AddImportsVisitor.add_needed_import(context, package, obj)
    return AddImportsVisitor(context).transform_module(module)


def _is_owner_guard(stmt: cst.BaseStatement, target: m.Comparison) -> bool:
    return isinstance(stmt, cst.If) and bool(m.findall(stmt.test, target))


def _strip_owner_check(
    body: list[cst.BaseStatement], target: m.Comparison
) -> list[cst.BaseStatement]:
    out: list[cst.BaseStatement] = []
    for stmt in body:
        if isinstance(stmt, cst.If) and _is_owner_guard(stmt, target):
            test = _without(stmt.test, target)
            if test is None:
                continue  # the whole statement was the owner check
            stmt = stmt.with_changes(test=test)
        out.append(stmt)
    return out


def _load_index(body: list[cst.BaseStatement], t: Template) -> int | None:
    load = m.SimpleStatementLine(
        body=[
            m.Assign(
                targets=[m.AssignTarget(target=m.Name(t.var or ""))],
                value=m.Call(
                    func=m.Attribute(attr=m.Name("get")),
                    args=[
                        m.Arg(value=m.Name(t.model or "")),
                        m.Arg(value=m.Name(t.id_param or "")),
                    ],
                ),
            )
        ]
    )
    return next((i for i, s in enumerate(body) if m.matches(s, load)), None)


# --- authorization operators ---------------------------------------------------------------------


class DropOwnerCheck(Operator):
    name = "drop_owner_check"
    label = "vulnerable"
    family = Family.AUTHORIZATION
    cwe = 639
    description = "Remove the comparison between the resource owner and the caller."

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        fn = _handler(module, template.handler)
        target = _owner_comparison(template)
        if not any(_is_owner_guard(s, target) for s in _statements(fn)):
            return None
        body = _strip_owner_check(_statements(fn), target)
        return _replace_handler(module, fn.with_changes(body=fn.body.with_changes(body=body)))


class _SwapOwnerField(cst.CSTTransformer):
    def __init__(self, target: m.Comparison, field: str) -> None:
        self.target, self.field = target, field

    def leave_Comparison(
        self, original_node: cst.Comparison, updated_node: cst.Comparison
    ) -> cst.Comparison:
        if not m.matches(original_node, self.target):
            return updated_node
        if not isinstance(updated_node.left, cst.Attribute):
            return updated_node
        left = updated_node.left.with_changes(attr=cst.Name(self.field))
        return updated_node.with_changes(left=left)


class WrongField(Operator):
    name = "wrong_field"
    label = "vulnerable"
    family = Family.AUTHORIZATION
    cwe = 639
    description = "Compare the caller with the wrong field of the resource."

    def applies_to(self, template: Template) -> bool:
        return super().applies_to(template) and bool(template.wrong_field)

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        fn = _handler(module, template.handler)
        new = fn.visit(_SwapOwnerField(_owner_comparison(template), template.wrong_field or ""))
        if not isinstance(new, cst.FunctionDef):
            return None
        return _replace_handler(module, new)


class QueryScopeEquivalent(Operator):
    name = "query_scope_equivalent"
    label = "safe"
    family = Family.AUTHORIZATION
    cwe = 639
    description = "Express ownership as a filter in the query instead of a comparison."

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        fn = _handler(module, template.handler)
        body = _statements(fn)
        index = _load_index(body, template)
        if index is None:
            return None
        load = body[index]
        if not isinstance(load, cst.SimpleStatementLine):
            return None
        assign = load.body[0]
        if not isinstance(assign, cst.Assign) or not isinstance(assign.value, cst.Call):
            return None
        func = assign.value.func
        if not isinstance(func, cst.Attribute):
            return None
        session = _code(func.value)
        t = template
        body[index] = cst.parse_statement(
            f"{t.var} = {session}.scalars(select({t.model}).where("
            f"{t.model}.id == {t.id_param}, {t.model}.{t.owner_field} == {t.principal}.id"
            ")).first()\n"
        )
        body = _strip_owner_check(body, _owner_comparison(template))
        new = fn.with_changes(body=fn.body.with_changes(body=body))
        return _add_import(_replace_handler(module, new), "sqlalchemy", "select")


class MoveToDependency(Operator):
    name = "move_to_dependency"
    label = "safe"
    family = Family.AUTHORIZATION
    cwe = 639
    description = "Move the load and the owner check into a FastAPI dependency."

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        t = template
        fn = _handler(module, t.handler)
        body = _statements(fn)
        start = _load_index(body, t)
        target = _owner_comparison(t)
        end = next((i for i, s in enumerate(body) if _is_owner_guard(s, target)), None)
        if start is None or end is None or end < start:
            return None
        params = {p.name.value: p for p in fn.params.params}
        id_param, principal = params.get(t.id_param or ""), params.get(t.principal or "")
        session = next(
            (
                p
                for p in fn.params.params
                if p.annotation is not None and _code(p.annotation.annotation) == "Session"
            ),
            None,
        )
        if id_param is None or principal is None or session is None or fn.returns is None:
            return None

        def param(p: cst.Param) -> str:
            return _code(p.with_changes(comma=cst.MaybeSentinel.DEFAULT)).strip()

        newline = chr(10)
        moved = newline.join(_code(s).rstrip(newline) for s in body[start : end + 1])
        rest = newline.join(_code(s).rstrip(newline) for s in body[end + 1 :])
        dependency = f"owned_{t.var}"
        dep_params = "".join(f"    {param(p)},{newline}" for p in (id_param, principal, session))
        dep_source = (
            f"def {dependency}({newline}{dep_params}) -> {t.model}:{newline}"
            f"{textwrap.indent(moved, '    ')}{newline}    return {t.var}{newline}"
        )

        plain: list[str] = []
        defaulted: list[str] = []
        for p in fn.params.params:
            if p is id_param:
                defaulted.append(f"{t.var}: {t.model} = Depends({dependency})")
            elif p in (principal, session) and not re.search(rf"\b{p.name.value}\b", rest):
                continue  # no longer used by the handler
            elif p.default is None:
                plain.append(param(p))
            else:
                defaulted.append(param(p))
        handler_params = "".join(f"    {p},{newline}" for p in plain + defaulted)
        decorators = "".join(_code(d) for d in fn.decorators)
        handler_source = (
            f"{decorators}def {t.handler}({newline}{handler_params}) -> "
            f"{_code(fn.returns.annotation)}:{newline}"
            f"{textwrap.indent(rest, '    ')}{newline}"
        )
        position = module.body.index(fn)
        before = "".join(_code(s) for s in module.body[:position])
        after = "".join(_code(s) for s in module.body[position + 1 :])
        header = _code(module.with_changes(body=[]))
        gap = newline * 3  # two blank lines between top-level definitions
        return cst.parse_module(
            f"{header}{before.rstrip(newline)}{gap}{dep_source}{gap[1:]}{handler_source}{after}"
        )


# --- injection operators -----------------------------------------------------------------------


@dataclass(frozen=True)
class _SqlCall:
    execute: cst.Call  # db.execute(text(...), {...})
    literal: cst.SimpleString | cst.ConcatenatedString
    sql: str
    params: cst.Dict | None


def _string_pieces(literal: cst.BaseExpression) -> list[cst.SimpleString]:
    """The parts of an implicitly concatenated string, in order."""
    if isinstance(literal, cst.ConcatenatedString):
        return _string_pieces(literal.left) + _string_pieces(literal.right)
    if isinstance(literal, cst.SimpleString):
        return [literal]
    raise TypeError(f"not a plain string literal: {type(literal).__name__}")


class _FindSql(cst.CSTVisitor):
    def __init__(self) -> None:
        self.found: list[cst.Call] = []

    def visit_Call(self, node: cst.Call) -> None:
        if (
            m.matches(node.func, m.Attribute(attr=m.Name("execute")))
            and node.args
            and m.matches(node.args[0].value, m.Call(func=m.Name("text")))
        ):
            self.found.append(node)


def _sql_calls(fn: cst.FunctionDef) -> list[_SqlCall]:
    finder = _FindSql()
    fn.visit(finder)
    calls = []
    for call in finder.found:
        text_call = call.args[0].value
        if not isinstance(text_call, cst.Call):
            continue
        literal = text_call.args[0].value
        if not isinstance(literal, cst.SimpleString | cst.ConcatenatedString):
            continue
        # Parenthesized so a string split over several lines is one expression.
        sql = ast.literal_eval(f"({_code(literal)})")
        params = call.args[1].value if len(call.args) > 1 else None
        calls.append(_SqlCall(call, literal, sql, params if isinstance(params, cst.Dict) else None))
    return calls


def _element(params: cst.Dict, key: str) -> cst.DictElement | None:
    for el in params.elements:
        if (
            isinstance(el, cst.DictElement)
            and isinstance(el.key, cst.SimpleString)
            and el.key.evaluated_value == key
        ):
            return el
    return None


class _ReplaceCall(cst.CSTTransformer):
    def __init__(self, old: cst.Call, new: cst.BaseExpression) -> None:
        self.old, self.new = old, new

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        return self.new if original_node is self.old else updated_node


class SqlFString(Operator):
    name = "sql_fstring"
    label = "vulnerable"
    family = Family.INJECTION
    cwe = 89
    description = "Inline the request value into the SQL text with an f-string."

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        fn = _handler(module, template.handler)
        param = template.param or ""
        for call in _sql_calls(fn):
            if call.params is None or (el := _element(call.params, param)) is None:
                continue
            if not re.search(rf":{param}\b", call.sql) or '"' in call.sql:
                continue
            value = el.value
            if isinstance(value, cst.FormattedString):
                inline = "".join(_code(part) for part in value.parts)
            else:
                inline = "{" + _code(value) + "}"
            quoted = f"'{inline}'"
            # Rewrite only the string piece that holds the parameter, keeping the
            # original split so line lengths do not differ from the safe variants.
            pieces = []
            for piece in _string_pieces(call.literal):
                text_value = ast.literal_eval(_code(piece))
                if re.search(rf":{param}\b", text_value):
                    escaped = text_value.replace("{", "{{").replace("}", "}}")
                    inlined = re.sub(rf":{param}\b", lambda _, q=quoted: q, escaped)
                    pieces.append(f'f"{inlined}"')
                else:
                    pieces.append(_code(piece))
            joined = " ".join(pieces)
            args: list[cst.Arg] = [cst.Arg(cst.parse_expression(f"text({joined})"))]
            remaining = [e for e in call.params.elements if e is not el]
            if remaining:
                fixed = [e.with_changes(comma=cst.MaybeSentinel.DEFAULT) for e in remaining]
                args.append(cst.Arg(call.params.with_changes(elements=fixed)))
            new = fn.visit(_ReplaceCall(call.execute, call.execute.with_changes(args=args)))
            if isinstance(new, cst.FunctionDef):
                return _replace_handler(module, new)
        return None


class BoundParameters(Operator):
    name = "bound_parameters"
    label = "safe"
    family = Family.INJECTION
    cwe = 89
    description = "Bind the parameters with text(...).bindparams(...) instead of a dict."

    def mutate(self, module: cst.Module, template: Template) -> cst.Module | None:
        fn = _handler(module, template.handler)
        for call in _sql_calls(fn):
            if call.params is None:
                continue
            pairs = []
            for el in call.params.elements:
                if not isinstance(el, cst.DictElement) or not isinstance(el.key, cst.SimpleString):
                    return None
                key = el.key.evaluated_value
                if not isinstance(key, str) or not key.isidentifier():
                    return None
                pairs.append(f"{key}={_code(el.value)}")
            text_code = _code(call.execute.args[0].value)
            bound = cst.parse_expression(f"{text_code}.bindparams({', '.join(pairs)})")
            new = fn.visit(
                _ReplaceCall(call.execute, call.execute.with_changes(args=[cst.Arg(bound)]))
            )
            if isinstance(new, cst.FunctionDef):
                return _replace_handler(module, new)
        return None


OPERATORS: tuple[Operator, ...] = (
    DropOwnerCheck(),
    WrongField(),
    QueryScopeEquivalent(),
    MoveToDependency(),
    SqlFString(),
    BoundParameters(),
)

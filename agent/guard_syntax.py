"""Conservative executable guard candidates. Parsing never executes target code.

These facts prove a recognized check's syntax and local enforcement, not its policy.
The model supplies the policy kind. Unsupported control flow remains visible upstream.
"""

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

from agent.evidence import Cut
from agent.ts_role_guards import _module
from analysis.syntax import _parser, _text, _walk, code_only, extract
from backend.contracts.code import GuardMechanism
from backend.contracts.common import Language

NAME = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"


@dataclass(frozen=True)
class Check:
    start: int
    end: int
    focus: int
    mechanism: GuardMechanism
    pairs: tuple[tuple[str, str], ...] = ()
    roles: tuple[str, ...] = ()
    role_parameter: str | None = None
    authentication: bool = False
    context: tuple[Cut, ...] = ()
    resource: str | None = None

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(side for pair in self.pairs for side in pair))


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := _dotted(node.value)):
        return f"{base}.{node.attr}"
    return None


def _atoms(node: ast.expr) -> list[ast.expr]:
    # Rejecting any mismatch joined by OR enforces every equality on continuation.
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return [atom for value in node.values for atom in _atoms(value)]
    return [node]


def _python(source: bytes) -> list[Check]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    checks = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        # Only unconditional statements in the function body dominate its continuation.
        for statement in function.body:
            if isinstance(statement, ast.Return | ast.Raise):
                break
            if isinstance(statement, ast.If | ast.Try | ast.For | ast.While | ast.With) and any(
                isinstance(node, ast.Return | ast.Yield | ast.YieldFrom)
                for node in ast.walk(statement)
            ):
                break
            if isinstance(statement, ast.If):
                if statement.orelse or len(statement.body) != 1:
                    continue
                denial = statement.body[0]
                if not isinstance(denial, ast.Raise) or not isinstance(denial.exc, ast.Call):
                    continue
                call = denial.exc
                if _dotted(call.func) != "HTTPException":
                    continue
                statuses = [kw.value for kw in call.keywords if kw.arg == "status_code"]
                if len(statuses) != 1 or not isinstance(statuses[0], ast.Constant):
                    continue
                status = statuses[0].value
                if status not in (401, 403, 404):
                    continue
                for atom in _atoms(statement.test):
                    if not isinstance(atom, ast.Compare) or len(atom.ops) != 1:
                        continue
                    left, right = atom.left, atom.comparators[0]
                    a, b = _dotted(left), _dotted(right)
                    roots = {name.split(".")[0] for name in (a, b) if name}
                    earlier = function.body[: function.body.index(statement)]
                    exposed = False
                    for prior in earlier:
                        for action in ast.walk(prior):
                            if isinstance(action, ast.Expr) and isinstance(action.value, ast.Call):
                                args = [
                                    *action.value.args,
                                    *(kw.value for kw in action.value.keywords),
                                ]
                                if any(
                                    isinstance(n, ast.Name) and n.id in roots
                                    for arg in args
                                    for n in ast.walk(arg)
                                ):
                                    exposed = True
                            if isinstance(action, ast.Assign | ast.AnnAssign | ast.AugAssign):
                                targets = (
                                    action.targets
                                    if isinstance(action, ast.Assign)
                                    else [action.target]
                                )
                                if any(
                                    isinstance(t, ast.Attribute)
                                    and (name := _dotted(t)) is not None
                                    and name.split(".")[0] in roots
                                    for t in targets
                                ):
                                    exposed = True
                    if exposed:
                        continue
                    pair = ((a, b),) if a and b and isinstance(atom.ops[0], ast.NotEq) else ()
                    roles: tuple[str, ...] = ()
                    parameter = None
                    if isinstance(atom.ops[0], ast.NotIn) and a:
                        if isinstance(right, ast.Tuple | ast.List | ast.Set):
                            if all(
                                isinstance(v, ast.Constant) and isinstance(v.value, str)
                                for v in right.elts
                            ):
                                roles = tuple(
                                    v.value
                                    for v in right.elts
                                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                                )
                        elif isinstance(right, ast.Name):
                            parameter = right.id
                    auth = (
                        status == 401
                        and isinstance(atom.ops[0], ast.Is | ast.Eq)
                        and isinstance(right, ast.Constant)
                        and right.value is None
                        and a is not None
                    )
                    if pair or roles or parameter or auth:
                        checks.append(
                            Check(
                                statement.lineno,
                                statement.end_lineno or statement.lineno,
                                atom.lineno,
                                GuardMechanism.COMPARISON,
                                pair,
                                roles,
                                parameter,
                                auth,
                            )
                        )
            # A SQLAlchemy predicate counts only inside an executed query, not a saved boolean.
            if not isinstance(statement, ast.Assign | ast.AnnAssign | ast.Expr):
                continue
            for query in ast.walk(statement):
                if not isinstance(query, ast.Call) or not isinstance(query.func, ast.Attribute):
                    continue
                if query.func.attr not in ("where", "filter_by"):
                    continue
                ancestor = parents.get(query)
                executed = None
                while ancestor is not None and ancestor is not statement:
                    if (
                        isinstance(ancestor, ast.Call)
                        and isinstance(ancestor.func, ast.Attribute)
                        and ancestor.func.attr in ("scalars", "scalar", "execute")
                    ):
                        executed = ancestor
                    ancestor = parents.get(ancestor)
                proof_start = executed.lineno if executed is not None else query.lineno
                proof_end = (
                    (executed.end_lineno or executed.lineno) if executed is not None else None
                )
                if (
                    executed is None
                    and isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                ):
                    binding = statement.targets[0].id
                    position = function.body.index(statement)
                    for later in function.body[position + 1 :]:
                        if not isinstance(later, ast.Return):
                            break
                        uses = [
                            call
                            for call in ast.walk(later)
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr in ("execute", "scalars", "scalar")
                            and len(call.args) == 1
                            and isinstance(call.args[0], ast.Name)
                            and call.args[0].id == binding
                        ]
                        if len(uses) == 1:
                            proof_end = later.end_lineno
                        break
                if proof_end is None:
                    continue
                pairs = []
                focus = None
                resource = None
                if query.func.attr == "filter_by":
                    selects = [
                        n
                        for n in ast.walk(query.func.value)
                        if isinstance(n, ast.Call)
                        and _dotted(n.func) == "select"
                        and len(n.args) == 1
                        and _dotted(n.args[0])
                    ]
                    if (
                        len(selects) != 1
                        or query.args
                        or any(k.arg is None for k in query.keywords)
                    ):
                        continue
                    resource = _dotted(selects[0].args[0])
                    for keyword in query.keywords:
                        if keyword.arg and isinstance(keyword.value, ast.Attribute):
                            bound = _dotted(keyword.value)
                            if bound:
                                pairs.append((keyword.arg, bound))
                                focus = keyword.value.lineno
                for arg in query.args:
                    if (
                        isinstance(arg, ast.Compare)
                        and len(arg.ops) == 1
                        and isinstance(arg.ops[0], ast.Eq)
                        and isinstance(arg.left, ast.Attribute)
                        and isinstance(arg.comparators[0], ast.Attribute)
                    ):
                        a, b = _dotted(arg.left), _dotted(arg.comparators[0])
                        if a and b:
                            pairs.append((a, b))
                            focus = arg.lineno
                if pairs:
                    checks.append(
                        Check(
                            proof_start,
                            proof_end,
                            focus or query.lineno,
                            GuardMechanism.QUERY_FILTER,
                            tuple(pairs),
                            resource=resource,
                        )
                    )
    return checks


def _sql_executors(
    source: bytes, language: Language, path: str, read: Callable[[str], bytes | None]
) -> set[str]:
    """Recognize source-defined wrappers that actually execute SQL with ordered rest args.

    No function is trusted by its name. This deliberately small wrapper recognizer
    rejects aliases/reexports/dynamic helpers it cannot prove from snapshot source.
    """
    found = set()
    facts = extract(path, language, source, set())
    for imported in facts.imports:
        if imported.name is None:
            continue
        # Reuse the exact frozen-source resolver used for role/ORM helpers.
        # Unknown, ambiguous or escaping JSON mappings remain unproved.
        target = _module(path, imported.module, read)
        helper = read(target) if target else None
        if helper is None or target is None:
            continue
        helper = code_only(Language.TYPESCRIPT, helper)
        helper_facts = extract(target, Language.TYPESCRIPT, helper, set())
        symbols = [s for s in helper_facts.symbols if s.name == imported.name and s.exported]
        if len(symbols) != 1:
            continue
        definitions = [
            n
            for n in _walk(_parser(Language.TYPESCRIPT).parse(helper).root_node)
            if n.type == "function_declaration"
            and _text(n.child_by_field_name("name")) == imported.name
        ]
        if len(definitions) != 1:
            continue
        block = definitions[0].child_by_field_name("body")
        if (
            block is None
            or len(block.named_children) != 1
            or block.named_children[0].type != "return_statement"
        ):
            continue
        body = "\n".join(
            helper.decode().splitlines()[symbols[0].start_line - 1 : symbols[0].end_line]
        )
        parameters = re.search(r"\(\s*(\w+)\s*:\s*string\s*,\s*\.\.\.(\w+)\s*:", body)
        if parameters is None:
            continue
        sql, params = parameters.groups()
        execution = re.search(
            rf"\breturn\s+(?:Number\()?\s*db\(\)\.prepare\({sql}\)"
            rf"\.(?:get|all|run)\(\.\.\.{params}\)",
            body,
        )
        # The connection factory must show a node:sqlite database construction.
        sqlite_import = any(
            i.module == "node:sqlite" and i.name == "DatabaseSync" for i in helper_facts.imports
        )
        if (
            execution
            and sqlite_import
            and b"new DatabaseSync(" in helper
            and b"return connection.db;" in helper
        ):
            found.add(imported.alias or imported.name)
    return found


def _typescript(source: bytes, language: Language, executors: set[str]) -> list[Check]:
    root = _parser(language).parse(source).root_node
    if root.has_error:
        return []
    checks = []
    for node in _walk(root):
        # Only direct statements in a function body are supported.
        if node.type == "if_statement":
            parent = node.parent
            if parent is None or parent.type != "statement_block" or parent.parent is None:
                continue
            if parent.parent.type not in (
                "function_declaration",
                "method_definition",
                "arrow_function",
            ):
                continue
            if any(
                s.type in ("return_statement", "throw_statement")
                for s in parent.named_children
                if s.end_byte <= node.start_byte
            ):
                continue
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if node.child_by_field_name("alternative") is not None:
                continue
            test, denial = _text(condition).strip("() "), _text(consequence).strip()
            if not re.fullmatch(r'(?:redirect\("/login"\)|notFound\(\));?', denial):
                continue
            # The imported framework function, not a locally shadowed name.
            terminator = denial.split("(", 1)[0]
            imports = [n for n in root.named_children if n.type == "import_statement"]
            if not any(
                '"next/navigation"' in _text(n) and re.search(rf"\b{terminator}\b", _text(n))
                for n in imports
            ):
                continue
            if re.fullmatch(rf"!{NAME}", test) and terminator == "redirect":
                checks.append(
                    Check(
                        node.start_point.row + 1,
                        node.end_point.row + 1,
                        node.start_point.row + 1,
                        GuardMechanism.COMPARISON,
                        authentication=True,
                    )
                )
        if node.type != "call_expression":
            continue
        if _text(node.child_by_field_name("function")) not in executors:
            continue
        ancestor = node.parent
        while ancestor is not None and ancestor.type not in ("statement_block", "program"):
            if ancestor.type in (
                "if_statement",
                "ternary_expression",
                "arrow_function",
                "binary_expression",
                "for_statement",
                "while_statement",
            ):
                break
            ancestor = ancestor.parent
        if (
            ancestor is None
            or ancestor.type != "statement_block"
            or ancestor.parent is None
            or ancestor.parent.type != "function_declaration"
        ):
            continue
        callee = _text(node.child_by_field_name("function"))
        parameters = _text(ancestor.parent.child_by_field_name("parameters"))
        if re.search(rf"\b{re.escape(callee)}\b", parameters):
            continue
        if any(
            s.type in ("return_statement", "throw_statement")
            for s in ancestor.named_children
            if s.end_byte <= node.start_byte
        ):
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            continue
        args = arguments.named_children
        sql_node = args[0]
        if sql_node.type not in ("string", "template_string"):
            continue
        sql = _text(sql_node)[1:-1]
        # A single leading constant SELECT fragment is allowed only when defined here.
        leading = re.match(r"^\$\{([A-Za-z_]\w*)\}", sql)
        if leading:
            name = leading[1]
            definition = re.search(rf"\bconst\s+{re.escape(name)}\s*=\s*`([^`]+)`", source.decode())
            if (
                definition is None
                or "${" in definition[1]
                or re.search(r"\bWHERE\b", definition[1], re.I)
            ):
                continue
            sql = definition[1] + sql[leading.end() :]
        table = re.match(r"\s*(?:SELECT\b.*?\bFROM|UPDATE)\s+([\w]+)\b", sql, re.I | re.S)
        if (
            "${" in sql
            or re.search(r"\b(?:OR|UNION|NOT|EXISTS)\b|--|/\*", sql, re.I)
            or table is None
        ):
            continue
        where = re.search(r"\bWHERE\b(.*)", sql, re.I | re.S)
        if where is None:
            continue
        pairs = []
        for match in re.finditer(rf"\b({NAME})\s*=\s*\?", where[1]):
            position = sql[: where.start(1) + match.end()].count("?") - 1
            if position + 1 >= len(args):
                continue
            bound = _text(args[position + 1])
            if "." in bound and re.fullmatch(NAME, bound):
                pairs.append((match[1], bound))
        if pairs:
            checks.append(
                Check(
                    node.start_point.row + 1,
                    node.end_point.row + 1,
                    sql_node.start_point.row + 1,
                    GuardMechanism.QUERY_FILTER,
                    tuple(pairs),
                    resource=table[1],
                )
            )
    return checks


def checks(
    language: Language,
    source: bytes,
    start: int,
    end: int,
    *,
    path: str = "",
    read: Callable[[str], bytes | None] | None = None,
) -> list[Check]:
    """Recognized enforced checks wholly inside an exact symbol span."""
    code = code_only(language, source)
    executors = (
        _sql_executors(code, language, path, read)
        if read and path and language is not Language.PYTHON
        else set()
    )
    found = _python(code) if language is Language.PYTHON else _typescript(code, language, executors)
    if read and path and language is not Language.PYTHON:
        from agent.ts_guard_forms import denial_checks, keyed_checks
        from agent.ts_role_guards import role_checks

        found.extend(keyed_checks(code, language, path, read))
        found.extend(denial_checks(code, language))
        found.extend(
            Check(
                c.start, c.end, c.focus, GuardMechanism.COMPARISON, roles=c.roles, context=c.context
            )
            for c in role_checks(code, language, path, read)
        )
    return [check for check in found if start <= check.start <= check.end <= end]

"""Bounded keyed ORM filters and mandatory field/role denials from frozen source."""

import re

from tree_sitter import Node

from agent.evidence import Cut
from agent.guard_syntax import NAME, Check
from agent.ts_role_guards import Read, _denial, _module
from analysis.syntax import _parser, _text, _walk, extract
from backend.contracts.code import GuardMechanism
from backend.contracts.common import Language

IDENT = r"[A-Za-z_$][\w$]*"


def _body(node: Node) -> Node | None:
    """The expression must execute as a direct statement of this function."""
    parent = node.parent
    while parent is not None and parent.type not in ("statement_block", "program"):
        if parent.type in (
            "if_statement",
            "ternary_expression",
            "arrow_function",
            "binary_expression",
            "for_statement",
            "while_statement",
            "try_statement",
        ):
            return None
        parent = parent.parent
    if (
        parent is None
        or parent.type != "statement_block"
        or parent.parent is None
        or parent.parent.type != "function_declaration"
    ):
        return None
    for prior in parent.named_children:
        if prior.end_byte > node.start_byte:
            break
        if prior.type in ("return_statement", "throw_statement", "try_statement"):
            return None
        if prior.type == "if_statement" and any(n.type == "return_statement" for n in _walk(prior)):
            consequence = prior.child_by_field_name("consequence")
            if (
                prior.child_by_field_name("alternative") is not None
                or consequence is None
                or not any(_denial(consequence, status) for status in (401, 403, 404))
            ):
                return None
    return parent


def _modified(root: Node, names: set[str]) -> bool:
    return any(
        n.type in ("assignment_expression", "augmented_assignment_expression", "update_expression")
        and any(re.search(rf"\b{re.escape(name)}\b", _text(n)) for name in names)
        for n in _walk(root)
    )


def _client(source: bytes, path: str, receiver: str, read: Read) -> tuple[Cut, ...]:
    """Prove a const instance of the imported ORM; no name-only trust or config execution."""
    facts = extract(path, Language.TYPESCRIPT, source, set())
    root = _parser(Language.TYPESCRIPT).parse(source).root_node
    if root.has_error or _modified(root, {receiver}):
        return ()
    if any(
        n.type == "call_expression"
        and re.search(rf"\b{re.escape(receiver)}\b", _text(n.child_by_field_name("arguments")))
        for n in _walk(root)
    ):
        return ()
    imported = [i for i in facts.imports if (i.alias or i.name) == receiver]
    if imported:
        if len(imported) != 1 or imported[0].name is None:
            return ()
        target = _module(path, imported[0].module, read)
        raw = read(target) if target else None
        if raw is None or target is None:
            return ()
        # Only the directly exported constant; no reexports, nested factories or aliases.
        exported = extract(target, Language.TYPESCRIPT, raw, set()).symbols
        if not any(s.name == imported[0].name and s.exported for s in exported):
            return ()
        return _client(raw, target, imported[0].name, lambda _: None)
    constructors = [
        i for i in facts.imports if i.module == "@prisma/client" and i.name == "PrismaClient"
    ]
    if len(constructors) != 1:
        return ()
    constructor = constructors[0].alias or "PrismaClient"
    if root.has_error or _modified(root, {receiver, constructor}):
        return ()
    declarations = [
        n
        for n in _walk(root)
        if n.type == "variable_declarator" and _text(n.child_by_field_name("name")) == receiver
    ]
    if len(declarations) != 1:
        return ()
    declaration = declarations[0]
    statement = declaration.parent
    if (
        statement is None
        or not _text(statement).startswith("const ")
        or not re.fullmatch(
            rf"new\s+{re.escape(constructor)}\(\)", _text(declaration.child_by_field_name("value"))
        )
    ):
        return ()
    # A client passed to arbitrary code can acquire a replacement delegate.
    if any(
        n.type == "call_expression"
        and re.search(rf"\b{re.escape(receiver)}\b", _text(n.child_by_field_name("arguments")))
        for n in _walk(root)
    ):
        return ()
    first = next(
        (
            n
            for n in root.named_children
            if n.type == "import_statement" and "@prisma/client" in _text(n)
        ),
        None,
    )
    if first is None:
        return ()
    return tuple(
        Cut(label, path, Language.TYPESCRIPT, source, n.start_point.row + 1, n.end_point.row + 1)
        for label, n in (("orm import", first), ("orm instance", statement))
    )


def keyed_checks(source: bytes, language: Language, path: str, read: Read) -> list[Check]:
    root = _parser(language).parse(source).root_node
    if root.has_error:
        return []
    found = []
    for node in _walk(root):
        if node.type != "call_expression" or (body := _body(node)) is None:
            continue
        match = re.fullmatch(
            rf"({IDENT})\.({IDENT})\.(findUnique|findFirst|findMany|update|delete)",
            _text(node.child_by_field_name("function")),
        )
        if match is None:
            continue
        receiver, resource, _ = match.groups()
        if body.parent is None:
            continue
        if re.search(
            rf"\b{re.escape(receiver)}\b", _text(body.parent.child_by_field_name("parameters"))
        ):
            continue
        if _modified(root, {receiver}):
            continue
        context = _client(source, path, receiver, read)
        if not context:
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None or len(arguments.named_children) != 1:
            continue
        arg = arguments.named_children[0]
        if arg.type != "object" or any(n.type != "pair" for n in arg.named_children):
            continue
        where = [
            n.child_by_field_name("value")
            for n in arg.named_children
            if _text(n.child_by_field_name("key")) == "where"
        ]
        if len(where) != 1 or where[0] is None or where[0].type != "object":
            continue
        predicates = where[0].named_children
        keys = [
            _text(n.child_by_field_name("key")) if n.type == "pair" else _text(n)
            for n in predicates
        ]
        if (
            len(keys) != len(set(keys))
            or any(k in ("OR", "NOT", "AND") for k in keys)
            or any(n.type not in ("pair", "shorthand_property_identifier") for n in predicates)
            or any(not re.fullmatch(IDENT, k) for k in keys)
        ):
            continue
        pairs = []
        for n, key in zip(predicates, keys, strict=True):
            value = _text(n.child_by_field_name("value")) if n.type == "pair" else key
            if "." in value and re.fullmatch(NAME, value):
                pairs.append((key, value))
        if pairs:
            found.append(
                Check(
                    node.start_point.row + 1,
                    node.end_point.row + 1,
                    node.start_point.row + 1,
                    GuardMechanism.QUERY_FILTER,
                    tuple(pairs),
                    context=context,
                    resource=resource,
                )
            )
    return found


def denial_checks(source: bytes, language: Language) -> list[Check]:
    root = _parser(language).parse(source).root_node
    if root.has_error:
        return []
    found = []
    response_shadowed = bool(
        re.search(
            r"\b(?:const|let|var|class|function|import)\s+(?:\{[^}]*\b)?Response\b", source.decode()
        )
    )
    for node in _walk(root):
        if node.type != "if_statement" or node.child_by_field_name("alternative") is not None:
            continue
        body = _body(node)
        denial = node.child_by_field_name("consequence")
        if body is None or body.parent is None or denial is None or response_shadowed:
            continue
        if re.search(r"\bResponse\b", _text(body.parent.child_by_field_name("parameters"))):
            continue
        if not any(_denial(denial, status) for status in (403, 404)):
            continue
        text = _text(node.child_by_field_name("condition")).strip()
        text = text[1:-1].strip() if text.startswith("(") and text.endswith(")") else text
        pairs, roles, role_roots, valid = [], [], set(), True
        for atom in re.split(r"\s*\|\|\s*", text):
            match = re.fullmatch(rf"({NAME})\s*!==?\s*({NAME}|[\"']{IDENT}[\"'])", atom)
            if match is None:
                valid = False
                break
            left, right = match.groups()
            if right.startswith(('"', "'")) and "." in left:
                roles.append(right[1:-1])
                role_roots.add(left.split(".")[0])
            elif "." in left and "." in right:
                pairs.append((left, right))
            else:
                valid = False
        roots = {s.split(".")[0] for pair in pairs for s in pair}
        if (
            not valid
            or not (pairs or roles)
            or len(set(roles)) > 1
            or _modified(body, roots | role_roots | {"Response"})
        ):
            continue
        found.append(
            Check(
                node.start_point.row + 1,
                node.end_point.row + 1,
                node.start_point.row + 1,
                GuardMechanism.COMPARISON,
                tuple(pairs),
                roles=tuple(roles),
            )
        )
    return found

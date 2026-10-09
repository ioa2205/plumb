"""Bounded TypeScript role-denial proofs from immutable source, never helper names.

Only an unconditional HTTP denial and a local const receiver produced by a
source-defined class factory are supported. Dynamic helpers stay unresolved.
"""

import json
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from tree_sitter import Node

from agent.evidence import Cut
from analysis.syntax import _parser, _text, _walk, code_only, extract
from backend.contracts.common import Language

Read = Callable[[str], bytes | None]
IDENT = r"[A-Za-z_$][\w$]*"


@dataclass(frozen=True)
class RoleCheck:
    start: int
    end: int
    focus: int
    roles: tuple[str, ...]
    context: tuple[Cut, ...]


def _join(base: str, target: str) -> str | None:
    if not target or "\\" in target or ":" in target or target.startswith("/"):
        return None
    result = posixpath.normpath(posixpath.join(base, target))
    return None if result == ".." or result.startswith("../") else result


def _module(path: str, specifier: str, read: Read) -> str | None:
    """Relative imports or one explicit nearest JSON path mapping; no config execution."""
    base = str(PurePosixPath(path).parent)
    target = _join(base, specifier) if specifier.startswith(".") else None
    if target is None and not specifier.startswith("."):
        for directory in PurePosixPath(path).parents:
            raw = read(str(directory / "tsconfig.json"))
            if raw is None:
                continue
            try:
                config = json.loads(raw)
                if not isinstance(config, dict) or config.get("extends"):
                    return None
                options = config.get("compilerOptions", {})
                mappings = options.get("paths", {})
                config_base = _join(str(directory), options.get("baseUrl", "."))
                if config_base is None:
                    return None
                matches = []
                for pattern, choices in mappings.items():
                    if not isinstance(choices, list) or len(choices) != 1:
                        continue
                    if pattern.count("*") != 1 or not isinstance(choices[0], str):
                        continue
                    prefix, suffix = pattern.split("*")
                    if specifier.startswith(prefix) and specifier.endswith(suffix):
                        middle = specifier[len(prefix) : len(specifier) - len(suffix) or None]
                        matches.append(_join(config_base, choices[0].replace("*", middle)))
                target = matches[0] if len(matches) == 1 else None
            except (ValueError, TypeError, AttributeError):
                return None
            break
    if target is None:
        return None
    choices = [target] if target.endswith(".ts") else [target + ".ts", target + "/index.ts"]
    existing = [candidate for candidate in choices if read(candidate) is not None]
    return existing[0] if len(existing) == 1 else None


def _declarations(root: Node, kind: str, name: str) -> list[Node]:
    return [
        n
        for outer in root.named_children
        for n in (
            [outer.child_by_field_name("declaration")]
            if outer.type == "export_statement"
            else [outer]
        )
        if n is not None and n.type == kind and _text(n.child_by_field_name("name")) == name
    ]


def _factory_context(
    source: bytes, path: str, factory: str, method: str, read: Read
) -> tuple[Cut, ...]:
    imported = [
        i
        for i in extract(path, Language.TYPESCRIPT, source, set()).imports
        if i.kind == "named" and (i.alias or i.name) == factory
    ]
    if len(imported) != 1 or imported[0].name is None:
        return ()
    helper_path = _module(path, imported[0].module, read)
    helper = read(helper_path) if helper_path else None
    if helper is None or helper_path is None:
        return ()
    code = code_only(Language.TYPESCRIPT, helper)
    root = _parser(Language.TYPESCRIPT).parse(code).root_node
    if root.has_error:
        return ()
    functions = _declarations(root, "function_declaration", imported[0].name)
    if (
        len(functions) != 1
        or functions[0].parent is None
        or functions[0].parent.type != "export_statement"
    ):
        return ()
    function = functions[0]
    if any(c.type == "async" for c in function.children):
        return ()
    body = function.child_by_field_name("body")
    if body is None:
        return ()
    returns = [n for n in _walk(body) if n.type == "return_statement"]
    constructors = []
    for returned in returns:
        text = _text(returned)
        if re.fullmatch(r"return\s+null\s*;?", text):
            continue
        match = re.fullmatch(
            rf"return\s+(?:{IDENT}\s*\?\s*)?new\s+({IDENT})\(([^;]*)\)(?:\s*:\s*null)?\s*;?", text
        )
        if match is None:
            return ()
        # No calls/assignment/spreads in constructor arguments or dynamic constructors.
        if not re.fullmatch(
            rf"\s*{IDENT}(?:\.{IDENT})*(?:\s*,\s*{IDENT}(?:\.{IDENT})*)*\s*", match[2]
        ):
            return ()
        constructors.append(match[1])
    if len(constructors) != 1:
        return ()
    classes = _declarations(root, "class_declaration", constructors[0])
    if len(classes) != 1:
        return ()
    cls = classes[0]
    class_body = cls.child_by_field_name("body")
    if class_body is None or any(n.type == "class_heritage" for n in cls.named_children):
        return ()
    members = class_body.named_children
    if len(members) != 2 or any(n.type != "method_definition" for n in members):
        return ()
    constructor = next(
        (n for n in members if _text(n.child_by_field_name("name")) == "constructor"), None
    )
    predicate = next((n for n in members if _text(n.child_by_field_name("name")) == method), None)
    if (
        constructor is None
        or predicate is None
        or _text(constructor.child_by_field_name("body")).strip() != "{}"
    ):
        return ()
    parameters = re.fullmatch(
        rf"\(\s*\.\.\.({IDENT})\s*:\s*{IDENT}\[\]\s*\)",
        _text(predicate.child_by_field_name("parameters")),
    )
    if parameters is None:
        return ()
    comparison = re.fullmatch(
        rf"\{{\s*return\s+{re.escape(parameters[1])}\.includes\(this\.({IDENT})\);?\s*\}}",
        _text(predicate.child_by_field_name("body")),
    )
    if comparison is None or not re.search(
        rf"\breadonly\s+{re.escape(comparison[1])}\s*:",
        _text(constructor.child_by_field_name("parameters")),
    ):
        return ()
    # Do not infer immutable behavior from type annotations when source mutates it.
    if any(
        n.type in ("assignment_expression", "augmented_assignment_expression", "update_expression")
        and re.search(rf"\b{re.escape(constructors[0])}\b", _text(n))
        for n in _walk(root)
    ):
        return ()
    if re.search(
        rf"\b{re.escape(constructors[0])}\b", _text(function.child_by_field_name("parameters"))
    ):
        return ()
    if any(
        n.type == "expression_statement" and any(c.type == "call_expression" for c in _walk(n))
        for n in root.named_children
    ):
        return ()
    return tuple(
        Cut(
            label,
            helper_path,
            Language.TYPESCRIPT,
            helper,
            node.start_point.row + 1,
            node.end_point.row + 1,
        )
        for label, node in (("role predicate", cls), ("receiver factory", function))
    )


def _denial(node: Node, status: int) -> bool:
    """Only a literal response that exits this function; no logging or conditional return."""
    if node.type == "statement_block" and len(node.named_children) == 1:
        node = node.named_children[0]
    return bool(
        re.fullmatch(
            rf'return\s+Response\.json\(\{{\s*{IDENT}\s*:\s*(?:"[^"\n]*"|\x27[^\x27\n]*\x27)\s*\}},\s*\{{\s*status\s*:\s*{status}\s*\}}\)\s*;?',
            _text(node),
        )
    )


def role_checks(source: bytes, language: Language, path: str, read: Read) -> list[RoleCheck]:
    root = _parser(language).parse(source).root_node
    if root.has_error:
        return []
    # A shadowed Response or reassigned property is not the platform HTTP response.
    if re.search(
        r"\b(?:const|let|var|class|function|import)\s+(?:\{[^}]*\b)?Response\b", source.decode()
    ):
        return []
    found = []
    for node in _walk(root):
        if node.type != "if_statement" or node.child_by_field_name("alternative") is not None:
            continue
        body = node.parent
        if (
            body is None
            or body.type != "statement_block"
            or body.parent is None
            or body.parent.type != "function_declaration"
        ):
            continue
        condition, denial = (
            node.child_by_field_name("condition"),
            node.child_by_field_name("consequence"),
        )
        if denial is None or not _denial(denial, 403):
            continue
        match = re.fullmatch(rf"\(\s*!({IDENT})\.({IDENT})\(([^()]*)\)\s*\)", _text(condition))
        if match is None:
            continue
        receiver, method, arguments = match.groups()
        roles = re.findall(r'["\x27]([A-Za-z_][\w-]*)["\x27]', arguments)
        if not roles or not re.fullmatch(
            r'\s*["\x27][A-Za-z_][\w-]*["\x27](?:\s*,\s*["\x27][A-Za-z_][\w-]*["\x27])*\s*',
            arguments,
        ):
            continue
        previous = [s for s in body.named_children if s.end_byte <= node.start_byte]
        # Exactly one const factory binding and (optionally) a null-receiver HTTP denial.
        if len(previous) not in (1, 2) or previous[0].type != "lexical_declaration":
            continue
        declaration = previous[0]
        binding = re.fullmatch(
            rf"const\s+{re.escape(receiver)}\s*=\s*({IDENT})\([\s\S]*\);?", _text(declaration)
        )
        if binding is None or len(declaration.named_children) != 1:
            continue
        initializer = declaration.named_children[0].child_by_field_name("value")
        if (
            initializer is None
            or initializer.type != "call_expression"
            or _text(initializer.child_by_field_name("function")) != binding[1]
        ):
            continue
        if len(previous) == 2:
            auth = previous[1]
            consequence = auth.child_by_field_name("consequence")
            if (
                auth.type != "if_statement"
                or auth.child_by_field_name("alternative") is not None
                or re.fullmatch(
                    rf"\(\s*!{re.escape(receiver)}\s*\)",
                    _text(auth.child_by_field_name("condition")),
                )
                is None
                or consequence is None
                or not _denial(consequence, 401)
            ):
                continue
        factory = binding[1]
        parameters = _text(body.parent.child_by_field_name("parameters"))
        if re.search(rf"\b(?:Response|{re.escape(factory)}|{re.escape(receiver)})\b", parameters):
            continue
        if any(
            n.type
            in ("assignment_expression", "augmented_assignment_expression", "update_expression")
            and re.search(rf"\b(?:Response|{re.escape(receiver)}|{re.escape(factory)})\b", _text(n))
            for n in _walk(root)
        ):
            continue
        context = _factory_context(source, path, factory, method, read)
        if not context:
            continue
        found.append(
            RoleCheck(
                declaration.start_point.row + 1,
                node.end_point.row + 1,
                node.start_point.row + 1,
                tuple(roles),
                context,
            )
        )
    return found

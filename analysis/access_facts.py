"""Language-independent access summaries. Inputs are symbolic, never evaluated."""

import re

from pydantic import Field

from backend.contracts.code import DataLayer, Operation
from backend.contracts.common import Contract, RelPath


class Parameter(Contract):
    name: str
    index: int
    field: str = ""
    request_hint: str | None = None


class AccessFact(Contract):
    resource: str
    operation: Operation
    data_layer: DataLayer
    key_inputs: list[str]
    key_expression: str
    start_line: int
    end_line: int
    reason: str


class CallFact(Contract):
    line: int
    column: int
    arguments: list[list[str]]
    keywords: dict[str, list[str]] = Field(default_factory=dict)


class FunctionFacts(Contract):
    symbol_id: str
    parameters: list[Parameter]
    calls: list[CallFact]
    accesses: list[AccessFact]
    sql_calls: list["SQLCall"] = Field(default_factory=list)


class SQLSource(Contract):
    path: RelPath
    start_line: int
    end_line: int


class SQLCall(Contract):
    sql: str
    bindings: list[list[str]]
    start_line: int
    end_line: int
    evidence: list[SQLSource] = Field(default_factory=list)


def sql_access(
    sql: str, *, include_unkeyed: bool = False
) -> tuple[str, Operation, list[str | int]] | None:
    """Small SQL recognizer for literal table/key equality, not a SQL interpreter.

    Strings/comments are replaced by spaces before matching. Bind positions retain
    their original order. Complex/dynamic identifiers are deliberately not guessed.
    """
    tokens = re.findall(
        r"--[^\n]*|/\*[\s\S]*?\*/|'(?:''|[^'])*'|\?|:[A-Za-z_]\w*|\$\d+|"
        r"[A-Za-z_]\w*|[.()=,]|[^\s]",
        sql,
    )
    words: list[str] = []
    binds: dict[str, str | int] = {}
    position = 0
    for lexeme in tokens:
        if lexeme.startswith(("'", "--", "/*")):
            words.append("__literal__")
        elif lexeme == "?" or lexeme.startswith((":", "$")):
            marker = f"__bind_{len(binds)}__"
            binds[marker] = (
                position
                if lexeme == "?"
                else int(lexeme[1:]) - 1
                if lexeme.startswith("$")
                else lexeme[1:]
            )
            position += lexeme == "?"
            words.append(marker)
        else:
            words.append(lexeme)
    text = " ".join(words)
    match = re.match(r"(?i)\s*(SELECT\b.*?\bFROM|UPDATE|DELETE\s+FROM)\s+([A-Za-z_]\w*)\b", text)
    if not match:
        return None
    if " WHERE " not in text.upper():
        return (
            (match[2], Operation.LIST, [])
            if include_unkeyed and match[1].upper().startswith("SELECT")
            else None
        )
    operation = (
        Operation.READ
        if match[1].upper().startswith("SELECT")
        else Operation.UPDATE
        if match[1].upper() == "UPDATE"
        else Operation.DELETE
    )
    where = re.split(r"(?i)\bWHERE\b", text, maxsplit=1)[1]
    keys = re.findall(
        r"(?i)\b(?:[A-Za-z_]\w*\s*\.\s*)?(id|[A-Za-z_]\w*_id)\s*=\s*(__bind_\d+__)\b", where
    )
    primary = [marker for field, marker in keys if field.lower() == "id"]
    selected = primary or [marker for _, marker in keys]
    if not selected:
        return (
            (match[2], Operation.LIST, [])
            if include_unkeyed and operation is Operation.READ
            else None
        )
    return match[2], operation, [binds[k] for k in selected]

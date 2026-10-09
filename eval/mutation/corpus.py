"""Build the labeled corpus: every template plus every applicable operator variant."""

import functools
import hashlib
import subprocess
import sys
from dataclasses import dataclass

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from backend.contracts.common import Family
from eval.mutation.operators import OPERATORS, Label, Operator
from eval.mutation.templates import Template, load_templates

ORIGINAL = "original"


@dataclass(frozen=True)
class Variant:
    id: str  # "<template>/<operator>"
    template: str  # the template family: the unit for splits and the bootstrap
    operator: str  # "original" for the unmodified template
    family: Family
    label: Label
    cwe: int | None
    source: str
    handler: str
    handler_lines: tuple[int, int]  # first decorator line to last line of the handler
    sha256: str


class FormatError(RuntimeError):
    """ruff could not format a generated variant."""


@functools.lru_cache(maxsize=1024)
def normalize(source: str) -> str:
    """Format with ruff so no label carries a formatting tell (long lines, odd wrapping)."""
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--line-length", "100", "-"],
        input=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        raise FormatError(done.stderr.strip())
    return done.stdout


def handler_lines(source: str, handler: str) -> tuple[int, int]:
    wrapper = MetadataWrapper(cst.parse_module(source))
    positions = wrapper.resolve(PositionProvider)
    for node in wrapper.module.body:
        if isinstance(node, cst.FunctionDef) and node.name.value == handler:
            start = positions[node.decorators[0]].start.line if node.decorators else None
            span = positions[node]
            return (start or span.start.line, span.end.line)
    raise LookupError(f"handler {handler} not found")


def _variant(template: Template, operator: Operator | None, raw: str) -> Variant:
    name = operator.name if operator else ORIGINAL
    source = normalize(raw)
    return Variant(
        id=f"{template.name}/{name}",
        template=template.name,
        operator=name,
        family=template.family,
        label=operator.label if operator else "safe",
        cwe=operator.cwe if operator else None,
        source=source,
        handler=template.handler,
        handler_lines=handler_lines(source, template.handler),
        sha256=hashlib.sha256(source.encode()).hexdigest(),
    )


def build(templates: list[Template] | None = None) -> list[Variant]:
    templates = templates if templates is not None else load_templates()
    variants = []
    for template in templates:
        variants.append(_variant(template, None, template.source))
        for operator in OPERATORS:
            source = operator.apply(template)
            if source is not None:
                variants.append(_variant(template, operator, source))
    return variants

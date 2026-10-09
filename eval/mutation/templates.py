"""Safe handler templates and their manifest."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from backend.contracts.common import Family

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


class Template(BaseModel):
    """One safe handler. Authorization templates name their guard parts;
    injection templates name the request-controlled bound parameter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    family: Family
    handler: str
    # authorization templates
    var: str | None = None
    model: str | None = None
    id_param: str | None = None
    owner_field: str | None = None
    principal: str | None = None
    wrong_field: str | None = None
    # injection templates
    param: str | None = None
    source: str = ""

    @property
    def path(self) -> Path:
        return TEMPLATE_DIR / f"{self.name}.py"


def load_templates(directory: Path = TEMPLATE_DIR) -> list[Template]:
    manifest = tomllib.loads((directory / "templates.toml").read_text(encoding="utf-8"))
    templates = []
    for entry in manifest["templates"]:
        source = (directory / f"{entry['name']}.py").read_text(encoding="utf-8")
        templates.append(Template.model_validate({**entry, "source": source}))
    names = [t.name for t in templates]
    if len(names) != len(set(names)):
        raise ValueError("template names must be unique")
    return templates

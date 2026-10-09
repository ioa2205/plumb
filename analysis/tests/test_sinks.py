from pathlib import Path

import pytest

from analysis.sinks import sinks

LAB = Path(__file__).resolve().parents[2] / "labs/tandir/api/tandir/routers"


def test_tandir_sink_forms() -> None:
    facts = {s.function: s for p in LAB.glob("*.py") for s in sinks(p.read_bytes())}
    assert facts["search_orders"].risky
    assert facts["search_customers"].mechanism == "allowlisted"
    assert facts["print_cake_label"].risky
    assert facts["print_receipt"].mechanism == "parameterized"
    assert facts["download_photo"].risky
    assert facts["get_avatar"].mechanism == "contained"


@pytest.mark.parametrize(
    "change",
    [
        "path = root / name",
        "if path.is_relative_to(root):\n        raise HTTPException(status_code=404)",
        "if not path.is_relative_to(root):\n        pass",
        "if not path.is_relative_to(root) and not path.is_file():\n"
        "        raise HTTPException(status_code=404)",
        "if not path.is_relative_to(root):\n        raise HTTPException(status_code=404)\n"
        "    path = root / name",
        "if not path.is_relative_to(root):\n        raise HTTPException(status_code=404)\n"
        "    root = request.app.state.settings.other_dir.resolve()",
    ],
)
def test_containment_requires_canonical_path_mandatory_denial_and_stable_bindings(
    change: str,
) -> None:
    source = (LAB / "files.py").read_text()
    if change.startswith("path ="):
        source = source.replace("path = (root / name).resolve()", change)
    else:
        source = source.replace(
            "if not path.is_relative_to(root) or not path.is_file():\n"
            '        raise HTTPException(status_code=404, detail="Avatar not found")',
            change,
        )
    assert sinks(source.encode())[0].mechanism != "contained"


@pytest.mark.parametrize(
    "change",
    [
        "if column is None:\n        pass",
        "if column is not None:\n        raise HTTPException(status_code=400)",
        "if column is None:\n        raise HTTPException(status_code=400)\n    column = sort",
    ],
)
def test_sql_allowlist_must_deny_unknown_values_and_keep_the_binding(change: str) -> None:
    source = (
        (LAB / "admin.py")
        .read_text()
        .replace(
            "if column is None:\n"
            '        raise HTTPException(status_code=400, detail="Unknown sort")',
            change,
        )
    )
    assert (
        next(s for s in sinks(source.encode()) if s.function == "search_customers").mechanism
        != "allowlisted"
    )


@pytest.mark.parametrize(
    "change", ["shell=True,", "shell=enabled,", "**options,", "executable=customer,"]
)
def test_command_argument_array_is_not_enough_when_shell_or_executable_is_dynamic(
    change: str,
) -> None:
    source = (
        (LAB / "kitchen.py")
        .read_text()
        .replace(
            "check=True,\n        timeout=10,",
            f"{change}\n        check=True,\n        timeout=10,",
        )
    )
    assert (
        next(s for s in sinks(source.encode()) if s.function == "print_receipt").mechanism
        != "parameterized"
    )


def test_shadowed_imports_and_comments_cannot_establish_safety() -> None:
    source = b"""import subprocess
def f(customer):
    subprocess = customer
    # subprocess.run(["safe", customer])
    subprocess.run(["safe", customer])
"""
    assert not sinks(source)


@pytest.mark.parametrize("escape", ["alias = SORTS", "consume(SORTS)", "SORTS.update(other)"])
def test_escaped_or_mutated_allowlist_cannot_acquit(escape: str) -> None:
    source = f"""from sqlalchemy import text
SORTS = {{"id": "id"}}
{escape}
def f(db, sort):
    column = SORTS.get(sort)
    if column is None:
        raise ValueError()
    return db.execute(text(f"SELECT id FROM users ORDER BY {{column}}"))
"""  # noqa: S608 - parsed source only, never executed
    assert sinks(source.encode())[0].mechanism != "allowlisted"


@pytest.mark.parametrize(
    "extra",
    [
        "if name:\n        path = root / name",
        "path /= name",
        "path: object = root / name",
        "path.is_relative_to = custom",
    ],
)
def test_unsupported_rebinding_cannot_establish_safety(extra: str) -> None:
    source = (
        (LAB / "files.py")
        .read_text()
        .replace("return FileResponse(path)", f"{extra}\n    return FileResponse(path)")
    )
    fact = sinks(source.encode())[0]
    assert fact.issues or fact.mechanism != "contained"


def test_stored_value_is_not_proven_controllable_by_a_numeric_selector() -> None:
    source = b"""import subprocess
def f(db, item_id):
    item = db.get(Item, item_id)
    subprocess.run(f"print {item.inscription}", shell=True)
"""
    assert sinks(source)[0].issues == ("Unresolved call or stored-value provenance",)

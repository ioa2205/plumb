from collections.abc import Iterator
from pathlib import Path

import pytest

from analysis.fastapi import Dependency, FastAPIMap, extract_fastapi
from analysis.index import Index, index_path
from analysis.resolution import LinkStatus
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.syntax import span_sha256

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[FastAPIMap, Index]]:
    cache = tmp_path_factory.mktemp("fastapi-map")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        yield extract_fastapi(snapshot, store, index), index
    finally:
        index.close()


# Independently enumerated application routes; no app import, HTTP or lab execution.
EXPECTED = {
    ("GET", "/health"): (),
    ("POST", "/auth/login"): ("get_db",),
    ("POST", "/auth/logout"): ("current_user", "get_db"),
    ("GET", "/auth/me"): ("current_user",),
    ("GET", "/orders"): ("current_user", "get_db"),
    ("POST", "/orders"): ("current_user", "get_db"),
    ("GET", "/orders/{order_id}"): ("current_user", "get_db"),
    ("GET", "/orders/{order_id}/receipt"): ("current_user", "get_db"),
    ("GET", "/orders/{order_id}/invoice"): ("current_user", "get_db"),
    ("POST", "/orders/{order_id}/cancel"): ("current_user", "get_db"),
    ("GET", "/orders/{order_id}/items"): ("owned_order",),
    ("GET", "/orders/{order_id}/tracking"): ("current_user", "get_db"),
    ("POST", "/orders/{order_id}/photos"): ("owned_order", "get_db"),
    ("GET", "/orders/{order_id}/photos"): ("current_user", "get_db"),
    ("GET", "/branches/{branch_id}/menu"): ("get_db",),
    ("PUT", "/branches/{branch_id}/menu/{item_id}"): ("check", "get_db"),
    ("PUT", "/branches/{branch_id}/hours"): ("check", "get_db"),
    ("GET", "/branches/{branch_id}/orders"): ("check", "get_db"),
    ("GET", "/admin/orders"): ("check", "get_db"),
    ("GET", "/admin/customers"): ("check", "get_db"),
    ("GET", "/admin/orders/{order_id}"): ("check", "get_db"),
    ("POST", "/kitchen/orders/{order_id}/items/{item_id}/label"): ("check", "get_db"),
    ("POST", "/kitchen/orders/{order_id}/receipt"): ("check", "get_db"),
    ("GET", "/avatars"): (),
    ("GET", "/courier/deliveries"): ("check", "get_db"),
    ("GET", "/courier/orders/{order_id}"): ("check", "get_db"),
}


def flatten(dependencies: list[Dependency]) -> Iterator[Dependency]:
    for dependency in dependencies:
        yield dependency
        yield from flatten(dependency.children)


def test_all_tandir_routes_and_direct_dependencies(tandir: tuple[FastAPIMap, Index]) -> None:
    result, index = tandir
    names = {s.id: s.name for s in index.symbols()}
    actual = {(r.entry.method, r.entry.route): r for r in result.routes}
    assert actual.keys() == EXPECTED.keys()
    assert len(result.routes) == 26 and len(result.routers) == 8
    assert not result.issues
    for key, expected in EXPECTED.items():
        route = actual[key]
        assert route.mount_status is LinkStatus.INFERRED
        assert (
            tuple(names[d.target_symbol_id] for d in route.dependencies if d.target_symbol_id)
            == expected
        )
        assert all(
            d.target_symbol_id and d.status is LinkStatus.INFERRED
            for d in flatten(route.dependencies)
        )


def test_every_tandir_dependency_chain(tandir: tuple[FastAPIMap, Index]) -> None:
    result, index = tandir
    names = {s.id: s.qualified_name for s in index.symbols()}
    expected = {
        "tandir.db.get_db": [],
        "tandir.security.current_user": ["tandir.db.get_db"],
        "tandir.security.require_role.check": ["tandir.security.current_user"],
        "tandir.services.orders.owned_order": ["tandir.security.current_user", "tandir.db.get_db"],
    }
    for route in result.routes:
        for dependency in flatten(route.dependencies):
            assert dependency.target_symbol_id
            assert [
                names[d.target_symbol_id] for d in dependency.children if d.target_symbol_id
            ] == expected[names[dependency.target_symbol_id]]


def test_role_factory_arguments_and_auth_signals_are_cited(
    tandir: tuple[FastAPIMap, Index],
) -> None:
    result, index = tandir
    role = index.symbol("tandir.security.require_role")
    assert role is not None
    admin = next(r for r in result.routes if r.entry.route == "/admin/orders/{order_id}")
    dependency = admin.dependencies[0]
    assert dependency.factory_symbol_id == role.id
    assert dependency.factory_arguments == ["'admin'"]
    assert [s.kind for s in dependency.auth_signals] == ["http_403_raise"]
    auth = dependency.children[0]
    assert [s.kind for s in auth.auth_signals] == ["http_401_raise", "http_401_raise"]
    for signal in [*dependency.auth_signals, *auth.auth_signals]:
        source = (TANDIR / signal.span.path).read_bytes()
        assert signal.span.content_sha256 == span_sha256(
            source, signal.span.start_line, signal.span.end_line
        )
    assert "confirmed" not in dependency.model_dump()  # classification belongs to M3
    assert FastAPIMap.model_validate_json(result.model_dump_json()) == result


def project(tmp_path: Path, files: dict[str, str]) -> tuple[FastAPIMap, dict[str, str]]:
    root = tmp_path / "project"
    for name, content in files.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    store = SnapshotStore(tmp_path / "snapshots")
    snapshot = take_snapshot(root, store)
    index = Index.build(snapshot, store, index_path(tmp_path, snapshot.id))
    try:
        return extract_fastapi(snapshot, store, index), {
            s.id: s.qualified_name for s in index.symbols()
        }
    finally:
        index.close()


def test_nested_mount_prefixes_and_all_dependency_scopes(tmp_path: Path) -> None:
    result, names = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import FastAPI as App, APIRouter as Router, Depends as D\n"
                "from typing import Annotated as A\n"
                "def global_dep(): pass\n"
                "def mount_dep(): pass\n"
                "def router_dep(): pass\n"
                "def decorator_dep(): pass\n"
                "def parameter_dep(): pass\n"
                "app = App(dependencies=[D(global_dep)])\n"
                "outer = Router(prefix='/outer')\n"
                "inner = Router(prefix='/inner', dependencies=[D(router_dep)])\n"
                "@inner.api_route('/items', methods=['GET', 'POST'], "
                "dependencies=[D(decorator_dep)])\n"
                "def route(user: A[str, D(parameter_dep)]): pass\n"
                "outer.include_router(inner, prefix='/v1')\n"
                "app.include_router(outer, prefix='/api', dependencies=[D(mount_dep)])\n"
            )
        },
    )
    assert not result.issues
    assert {r.entry.method for r in result.routes} == {"GET", "POST"}
    for route in result.routes:
        assert route.entry.route == "/api/outer/v1/inner/items"
        assert [names[d.target_symbol_id] for d in route.dependencies if d.target_symbol_id] == [
            "app.global_dep",
            "app.mount_dep",
            "app.router_dep",
            "app.decorator_dep",
            "app.parameter_dep",
        ]


def test_relative_imports_and_repeat_mounts(tmp_path: Path) -> None:
    result, _ = project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/routes.py": (
                "from fastapi import APIRouter\nrouter = APIRouter()\n"
                "@router.get('/item')\ndef route(): pass\n"
            ),
            "pkg/main.py": (
                "from fastapi import FastAPI\nfrom .routes import router as child\n"
                "app = FastAPI()\napp.include_router(child, prefix='/v1')\n"
                "app.include_router(child, prefix='/v2')\n"
            ),
        },
    )
    assert not result.issues
    assert {r.entry.route for r in result.routes} == {"/v1/item", "/v2/item"}
    assert len({r.entry.id for r in result.routes}) == 2


def test_cycles_dynamic_paths_and_unknown_dependencies_are_visible(tmp_path: Path) -> None:
    result, _ = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import FastAPI, APIRouter, Depends\n"
                "def a(x=Depends(b)): pass\n"
                "def b(x=Depends(a)): pass\n"
                "app=FastAPI()\nr=APIRouter(prefix=unknown)\n"
                "@r.get(dynamic_path)\ndef route(x=Depends(a), y=Depends(factory())): pass\n"
                "app.include_router(r)\nr.include_router(r)\n"
            )
        },
    )
    assert len(result.routes) == 1
    route = result.routes[0]
    assert route.entry.route is None and route.mount_status is LinkStatus.UNRESOLVED
    assert any(d.status is LinkStatus.UNRESOLVED for d in flatten(route.dependencies))
    assert any("Dependency cycle" in issue for issue in result.issues)
    assert any("router cycle" in issue for issue in result.issues)


def test_unmounted_and_conditional_routes_are_not_assumed_reachable(tmp_path: Path) -> None:
    result, _ = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import APIRouter\nr=APIRouter()\n"
                "@r.get('/known')\ndef route(): pass\n"
                "if condition:\n    @r.get('/conditional')\n    def other(): pass\n"
            )
        },
    )
    assert len(result.routes) == 1 and result.routes[0].mount_status is LinkStatus.UNRESOLVED
    assert any("conditional registration" in issue for issue in result.issues)
    assert any("no known app mount" in issue for issue in result.issues)


@pytest.mark.parametrize(
    "fake",
    [
        "class APIRouter:\n    pass\n",
        "def APIRouter():\n    pass\n",
    ],
)
def test_project_named_fastapi_is_not_the_external_framework(tmp_path: Path, fake: str) -> None:
    result, _ = project(
        tmp_path,
        {
            "fastapi.py": fake,
            "app.py": (
                "from fastapi import APIRouter\nr=APIRouter()\n@r.get('/x')\ndef route(): pass\n"
            ),
        },
    )
    assert not result.routes and not result.routers


def test_names_comments_and_shadowed_exception_names_are_not_auth_evidence(tmp_path: Path) -> None:
    result, names = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import FastAPI, Depends, HTTPException\n"
                "def require_owner():\n"
                "    # raise HTTPException(403); security reviewed\n    pass\n"
                "def pretend(HTTPException):\n    raise HTTPException(401)\n"
                "app=FastAPI()\n@app.get('/x')\n"
                "def route(user=Depends(require_owner), other=Depends(pretend)): pass\n"
            )
        },
    )
    assert len(result.routes) == 1
    deps = result.routes[0].dependencies
    assert [names[d.target_symbol_id] for d in deps if d.target_symbol_id] == [
        "app.require_owner",
        "app.pretend",
    ]
    assert all(not d.auth_signals for d in deps)


def test_security_dependency_keyword_only_and_implicit_callable(tmp_path: Path) -> None:
    result, names = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import FastAPI, Depends, Security\n"
                "def identity(): pass\n"
                "app=FastAPI()\n@app.get('/x')\n"
                "def route(user: identity=Depends(), *, "
                "staff=Security(dependency=identity, scopes=['read'])): pass\n"
            )
        },
    )
    assert len(result.routes[0].dependencies) == 2
    assert all(
        d.target_symbol_id and names[d.target_symbol_id] == "app.identity"
        for d in result.routes[0].dependencies
    )


def test_target_import_side_effect_never_runs(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    result, _ = project(
        tmp_path,
        {
            "app.py": (
                f"open({str(marker)!r}, 'w').write('BAD')\n"
                "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/x')\ndef route(): pass\n"
            )
        },
    )
    assert len(result.routes) == 1 and not marker.exists()


def test_rebound_factory_return_is_not_assumed_to_be_the_nested_function(tmp_path: Path) -> None:
    result, _ = project(
        tmp_path,
        {
            "app.py": (
                "from fastapi import FastAPI, Depends\n"
                "def factory():\n    def check(): pass\n    check = unknown\n    return check\n"
                "dep = factory()\napp=FastAPI()\n@app.get('/x')\n"
                "def route(user=Depends(dep)): pass\n"
            )
        },
    )
    assert result.routes[0].dependencies[0].status is LinkStatus.UNRESOLVED


def test_duplicate_modules_and_wildcard_imports_are_not_guessed(tmp_path: Path) -> None:
    result, _ = project(
        tmp_path,
        {
            "one/pkg/__init__.py": "",
            "two/pkg/__init__.py": "",
            "one/pkg/deps.py": "def identity(): pass\n",
            "two/pkg/deps.py": "def identity(): pass\n",
            "app.py": (
                "from fastapi import FastAPI, Depends\nfrom pkg.deps import identity\n"
                "app=FastAPI()\n@app.get('/x')\ndef route(user=Depends(identity)): pass\n"
            ),
            "unknown.py": (
                "from fastapi import FastAPI\nfrom elsewhere import *\n"
                "app=FastAPI()\n@app.get('/fake')\ndef fake(): pass\n"
            ),
        },
    )
    assert len(result.routes) == 1
    assert result.routes[0].dependencies[0].status is LinkStatus.UNRESOLVED
    assert any("wildcard import" in issue for issue in result.issues)

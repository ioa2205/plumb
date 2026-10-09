import io
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from analysis.index import Index, index_path
from analysis.python_resolution import resolve_python
from analysis.resolution import CallGraph, LinkStatus, graph_path
from analysis.snapshot import SnapshotStore, take_snapshot
from analysis.ty_client import (
    MAX_MESSAGE,
    TyLimits,
    TyUnavailable,
    isolated_environment,
    read_message,
    snapshot_server,
)
from backend.contracts.code import ProjectSnapshot

TANDIR = Path(__file__).resolve().parents[2] / "labs" / "tandir"


@pytest.fixture(scope="module")
def tandir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[CallGraph, Index]]:
    cache = tmp_path_factory.mktemp("python-resolution")
    store = SnapshotStore(cache / "snapshots")
    snapshot = take_snapshot(TANDIR, store)
    index = Index.build(snapshot, store, index_path(cache, snapshot.id))
    try:
        graph = resolve_python(snapshot, store, index, cache)
        yield graph, index
    finally:
        index.close()


@pytest.mark.parametrize(
    ("caller", "callee", "target"),
    [
        (
            "tandir.routers.orders.get_invoice",
            "load_order_scoped",
            "tandir.services.orders.load_order_scoped",
        ),
        (
            "tandir.routers.orders.download_photo",
            "load_order_scoped",
            "tandir.services.orders.load_order_scoped",
        ),
        (
            "tandir.routers.orders.track_order",
            "ensure_owner",
            "tandir.services.orders.ensure_owner",
        ),
        (
            "tandir.routers.orders.get_invoice",
            "InvoiceOut.from_order",
            "tandir.schemas.InvoiceOut.from_order",
        ),
        ("tandir.security.current_user", "_token", "tandir.security._token"),
        ("tandir.security.verify_password", "hash_password", "tandir.security.hash_password"),
    ],
)
def test_known_tandir_calls_use_ty(
    tandir: tuple[CallGraph, Index],
    caller: str,
    callee: str,
    target: str,
) -> None:
    graph, index = tandir
    assert not graph.issues
    caller_row, target_row = index.symbol(caller), index.symbol(target)
    assert caller_row is not None and target_row is not None
    edge = next(e for e in graph.calls(caller_row.id) if e.callee == callee)
    assert edge.status is LinkStatus.RESOLVED
    assert edge.via == "ty"
    assert edge.target_id == target_row.id
    assert edge in graph.callers(target_row.id)


def test_unknown_tandir_calls_are_retained(tandir: tuple[CallGraph, Index]) -> None:
    graph, index = tandir
    row = index.symbol("tandir.services.orders.load_order_scoped")
    assert row is not None
    edge = next(e for e in graph.calls(row.id) if e.callee == "db.scalars")
    assert edge.status is LinkStatus.UNRESOLVED and edge.target_id is None
    assert graph.peak_rss_bytes > 0
    assert graph.peak_rss_bytes < TyLimits().rss_bytes


def test_graph_cache_round_trip_and_snapshot_invariants(
    tandir: tuple[CallGraph, Index],
    tmp_path: Path,
) -> None:
    graph, _ = tandir
    path = graph_path(tmp_path, graph.snapshot_id, "python")
    graph.save(path)
    assert CallGraph.open(path) == graph
    edge = next(e for e in graph.edges if e.target_id)
    with pytest.raises(ValidationError, match="only unresolved"):
        type(edge).model_validate({**edge.model_dump(), "target_id": None})
    with pytest.raises(ValidationError, match="this snapshot"):
        CallGraph.model_validate({**graph.model_dump(), "snapshot_id": "a" * 64})
    with pytest.raises(ValueError, match="invalid snapshot"):
        graph_path(tmp_path, "../bad", "python")


def project(
    tmp_path: Path,
    sources: dict[str, str],
) -> tuple[ProjectSnapshot, SnapshotStore, Index]:
    root = tmp_path / "target"
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    store = SnapshotStore(tmp_path / "store")
    snapshot = take_snapshot(root, store)
    return snapshot, store, Index.build(snapshot, store, index_path(tmp_path, snapshot.id))


def run_project(
    tmp_path: Path,
    sources: dict[str, str],
    *,
    use_ty: bool = False,
) -> tuple[CallGraph, dict[str, str]]:
    snapshot, store, index = project(tmp_path, sources)
    try:
        graph = resolve_python(snapshot, store, index, tmp_path / "cache", use_ty=use_ty)
        names = {s.id: s.qualified_name for s in index.symbols()}
        return graph, names
    finally:
        index.close()


@pytest.mark.parametrize("use_ty", [False, True])
def test_import_aliases_relative_imports_reexports_and_unicode(
    tmp_path: Path,
    use_ty: bool,
) -> None:
    graph, names = run_project(
        tmp_path,
        {
            "pkg/__init__.py": "from .helper import charge as public\n",
            "pkg/helper.py": "def charge(value=1):\n    return value\n",
            "pkg/sub/__init__.py": "",
            "pkg/sub/main.py": (
                "from .. import public as alias\n"
                "import pkg.helper as service\n"
                "import pkg.helper\n"
                "def route():\n"
                "    label = '🍞'; alias()\n"
                "    service.charge()\n"
                "    pkg.helper.charge()\n"
            ),
        },
        use_ty=use_ty,
    )
    calls = [e for e in graph.edges if names[e.caller_id] == "pkg.sub.main.route"]
    assert len(calls) == 3
    assert all(names[e.target_id] == "pkg.helper.charge" for e in calls if e.target_id)
    assert all(e.target_id for e in calls)
    assert all(e.status is (LinkStatus.RESOLVED if use_ty else LinkStatus.INFERRED) for e in calls)
    assert calls[0].column == 18  # the non-BMP character takes two UTF-16 code units


@pytest.mark.parametrize(
    "body",
    [
        "def route(helper):\n    helper()\n",
        "def route():\n    helper = unknown\n    helper()\n",
        "def route():\n    helper()\n    helper = unknown\n",
        "def route():\n    global helper\n    helper()\n",
        "def route():\n    [helper() for helper in items]\n",
        "def route():\n    (lambda helper: helper())(unknown)\n",
        "if condition:\n    from pkg.helper import helper\ndef route():\n    helper()\n",
        "from unknown import *\ndef route():\n    helper()\n",
        "def route():\n    del helper\n    helper()\n",
        "def route():\n    try:\n        pass\n    except Exception as helper:\n        helper()\n",
        "def route():\n    match value:\n        case {'key': helper}:\n            helper()\n",
    ],
)
def test_shadowed_and_conditional_bindings_are_never_guessed(tmp_path: Path, body: str) -> None:
    graph, _ = run_project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/helper.py": "def helper():\n    pass\n",
            "pkg/main.py": "from pkg.helper import helper\n" + body,
        },
    )
    calls = [e for e in graph.edges if e.callee == "helper"]
    assert calls and all(e.status is LinkStatus.UNRESOLVED for e in calls)


def test_dynamic_calls_and_rebound_module_members_stay_unknown(tmp_path: Path) -> None:
    graph, _ = run_project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/helper.py": "def helper():\n    pass\n",
            "pkg/main.py": (
                "import pkg.helper as service\n"
                "def route(obj, registry):\n"
                "    service.helper = obj\n"
                "    service.helper()\n"
                "    obj.helper()\n"
                "    registry['helper']()\n"
            ),
        },
    )
    assert all(e.status is LinkStatus.UNRESOLVED for e in graph.edges)


def test_nested_local_calls_and_method_scope(tmp_path: Path) -> None:
    graph, names = run_project(
        tmp_path,
        {
            "main.py": (
                "def helper():\n    pass\n"
                "class Item:\n"
                "    def helper(self):\n        pass\n"
                "    def method(self):\n        helper()\n"
                "def route():\n"
                "    def nested():\n        helper()\n"
                "    nested()\n"
            )
        },
    )
    edges = {
        (names[e.caller_id], e.callee): names[e.target_id] if e.target_id else None
        for e in graph.edges
    }
    assert edges[("main.Item.method", "helper")] == "main.helper"
    assert edges[("main.route", "nested")] == "main.route.nested"
    assert edges[("main.route.nested", "helper")] == "main.helper"


def test_ty_resolves_typed_instance_dispatch_and_retains_ambiguity(tmp_path: Path) -> None:
    graph, names = run_project(
        tmp_path,
        {
            "main.py": (
                "class A:\n    def load(self):\n        pass\n"
                "class B:\n    def load(self):\n        pass\n"
                "def route(item: A):\n    item.load()\n"
                "def uncertain(item: A | B):\n    item.load()\n"
            )
        },
        use_ty=True,
    )
    known = next(e for e in graph.edges if names[e.caller_id] == "main.route")
    assert known.target_id and names[known.target_id] == "main.A.load"
    assert known.status is LinkStatus.RESOLVED
    uncertain = next(e for e in graph.edges if names[e.caller_id] == "main.uncertain")
    assert uncertain.status is LinkStatus.UNRESOLVED


@pytest.mark.parametrize("use_ty", [False, True])
def test_duplicate_module_roots_never_pick_one_arbitrarily(tmp_path: Path, use_ty: bool) -> None:
    graph, _ = run_project(
        tmp_path,
        {
            "one/pkg/__init__.py": "",
            "one/pkg/helper.py": "def helper():\n    pass\n",
            "two/pkg/__init__.py": "",
            "two/pkg/helper.py": "def helper():\n    pass\n",
            "main.py": "from pkg.helper import helper\ndef route():\n    helper()\n",
        },
        use_ty=use_ty,
    )
    assert graph.edges[0].status is LinkStatus.UNRESOLVED


def test_cyclic_reexports_and_invalid_relative_imports_terminate(tmp_path: Path) -> None:
    graph, _ = run_project(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from .b import helper\n",
            "pkg/b.py": "from .a import helper\n",
            "main.py": "from pkg.a import helper\nfrom .. import other\nhelper()\nother()\n",
        },
    )
    assert len(graph.edges) == 2
    assert all(e.status is LinkStatus.UNRESOLVED for e in graph.edges)


def test_failure_uses_labeled_fallback_and_syntax_errors_are_visible(tmp_path: Path) -> None:
    with patch("analysis.python_resolution.ty_references", side_effect=TyUnavailable("timeout")):
        graph, _ = run_project(
            tmp_path,
            {
                "main.py": "def helper():\n    pass\ndef route():\n    helper()\n",
                "broken.py": "def broken(:\n",
            },
            use_ty=True,
        )
    assert graph.edges[0].status is LinkStatus.INFERRED
    assert any("timeout" in issue for issue in graph.issues)
    assert any("broken.py" in issue for issue in graph.issues)


def test_snapshot_only_and_target_code_configuration_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    snapshot, store, index = project(
        tmp_path,
        {
            "main.py": (
                f"open({str(marker)!r}, 'w').write('BAD')\ndef helper():\n    pass\nhelper()\n"
            ),
            "sitecustomize.py": "raise RuntimeError('must never import target code')\n",
            "pyproject.toml": '[tool.ty.environment]\npython = "./target-python.exe"\n',
            "ty.toml": '[environment]\nroot = ["C:/"]\n',
            "plugin.pth": "import sitecustomize\n",
        },
    )
    (tmp_path / "target" / "main.py").write_text("not valid python!", encoding="utf-8")
    try:
        graph = resolve_python(snapshot, store, index, tmp_path / "cache")
        assert not graph.issues
        assert not marker.exists()
        assert any(e.callee == "helper" and e.status is LinkStatus.RESOLVED for e in graph.edges)
        assert not list((tmp_path / "cache" / "ty").iterdir())  # helper workspace is removed
        wrong = snapshot.model_copy(update={"id": "a" * 64})
        with pytest.raises(ValueError, match="same snapshot"):
            resolve_python(wrong, store, index, tmp_path)
    finally:
        index.close()


def test_lsp_workspace_is_source_only_and_environment_is_clean(tmp_path: Path) -> None:
    env = isolated_environment(tmp_path)
    assert env["PATH"] == ""
    assert not {"PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "TY_CONFIG_FILE"} & env.keys()
    sources = {"pkg/__init__.py": b"", "pkg/main.py": b"def helper():\n    pass\nhelper()\n"}
    with snapshot_server(sources, ["."], tmp_path) as client:
        assert {
            p.relative_to(client.root).as_posix() for p in client.root.rglob("*") if p.is_file()
        } == set(sources)
        assert client.references("pkg/main.py", 0, 4)
        outside = (tmp_path / "outside.py").as_uri()
        from analysis.python_resolution import _uri_key

        assert _uri_key(outside) != _uri_key((client.root / "pkg/main.py").as_uri())
        assert _uri_key("https://example.com/source.py") is None
        assert _uri_key("file://remote/share/main.py") is None


@pytest.mark.parametrize("sources", [{"../escape.py": b""}, {"ty.toml": b""}])
def test_staging_refuses_unsafe_paths_and_configuration(
    tmp_path: Path, sources: dict[str, bytes]
) -> None:
    with pytest.raises(ValueError), snapshot_server(sources, ["."], tmp_path):
        pytest.fail("should not launch")


def test_ty_time_budget_is_enforced(tmp_path: Path) -> None:
    with (
        pytest.raises(TyUnavailable, match=r"budget|timed out"),
        snapshot_server({"main.py": b"x = 1\n"}, ["."], tmp_path, TyLimits(total_seconds=0.000001)),
    ):
        pytest.fail("should time out")


def test_ty_memory_budget_kills_its_helper(tmp_path: Path) -> None:
    import time

    # The monitor samples at 50 ms. If initialization wins that race, make a
    # request after the first sample; either path must fail closed.
    with (
        pytest.raises(TyUnavailable, match="RSS budget"),
        snapshot_server(
            {"main.py": b"def helper():\n    pass\nhelper()\n"},
            ["."],
            tmp_path,
            TyLimits(rss_bytes=1),
        ) as client,
    ):
        time.sleep(0.15)
        client.references("main.py", 0, 4)


def test_wrong_ty_version_refuses_launch() -> None:
    from analysis.ty_client import trusted_binary

    with (
        patch("analysis.ty_client.version", return_value="0.0.0"),
        pytest.raises(TyUnavailable, match="requires ty"),
    ):
        trusted_binary()


def test_external_or_malformed_locations_are_not_evidence() -> None:
    from analysis.python_resolution import _location_key, _uri_key

    valid_uri = "file:///source/main.py"
    allowed = {_uri_key(valid_uri): "main.py"}
    position = {"start": {"line": 0, "character": 4}}
    assert _location_key({"uri": "file:///elsewhere/main.py", "range": position}, allowed) is None
    for location in [
        {"uri": valid_uri, "range": "bad"},
        {"uri": valid_uri, "range": {"start": []}},
        {"uri": valid_uri, "range": {"start": {"line": -1, "character": 0}}},
    ]:
        with pytest.raises(TyUnavailable):
            _location_key(location, allowed)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"Content-Length: -1\r\n\r\n",
        b"Content-Length: nope\r\n\r\n",
        f"Content-Length: {MAX_MESSAGE + 1}\r\n\r\n".encode(),
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
        b"Content-Length: 2\r\n\r\n{",
        b"Content-Length: 2\r\n\r\n[]",
        b"x" * 4097,
        b"Content-Length: 2\r\n\r\nxx",
    ],
)
def test_lsp_malformed_frames_fail_closed(raw: bytes) -> None:
    with pytest.raises(TyUnavailable):
        read_message(io.BytesIO(raw))


def test_lsp_valid_frame() -> None:
    raw = json.dumps({"id": 1, "result": []}).encode()
    assert read_message(io.BytesIO(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)) == {
        "id": 1,
        "result": [],
    }

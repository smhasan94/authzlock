"""Tests for SHA-243: FastAPI extraction, rule R10 and the gen-tests refusal.

Fixture tests run in a child process through the harness, like the Django fixtures; the
extractor's unit tests build small apps in-process, which needs no Django setup.
"""

from __future__ import annotations

import functools
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi import APIRouter, Depends, FastAPI, Security
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from starlette.applications import Starlette
from starlette.routing import Route as StarletteRoute

from authzlock.classify import classify_diff
from authzlock.diff import compute
from authzlock.errors import ProjectLoadError
from authzlock.extract.fastapi import callable_path, extract_app
from authzlock.fastapi_loader import load_app, parse_app
from authzlock.model import Inventory, Route
from harness import make_repo, project_env, run_cli, run_dump, run_extract

OAUTH2 = "fastapi.security.oauth2.OAuth2PasswordBearer"
BEARER = "fastapi.security.http.HTTPBearer"
FIXTURE_KEYS = {
    "GET /admin/reports/{report_id} -> main.get_report",
    "GET /admin/users -> main.list_users",
    "POST /items -> main.create_item",
    "GET /items -> main.list_items",
    "DELETE /items/{item_id} -> main.delete_item",
    "GET /legacy/status -> main.legacy_status",
    "GET,POST /search -> main.search",
    "any /static -> starlette.staticfiles.StaticFiles",
    "GET /token-info -> main.token_info",
    "WEBSOCKET /ws -> main.feed",
}


@pytest.fixture(scope="module")
def fixture_inventory() -> dict[str, Any]:
    return run_extract("fastapi_basic")


def _routes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {Route.from_dict(route).key(): route for route in document["routes"]}


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} not found exactly once in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# T2 ---------------------------------------------------------------------------------------


def test_t2_every_http_route_once_with_prefixes_and_methods(
    fixture_inventory: dict[str, Any],
) -> None:
    keys = [Route.from_dict(route).key() for route in fixture_inventory["routes"]]

    assert sorted(keys) == sorted(FIXTURE_KEYS)
    assert len(keys) == len(set(keys))
    routes = _routes(fixture_inventory)
    assert routes["GET /admin/reports/{report_id} -> main.get_report"]["name"] == "admin-report"
    assert routes["GET /legacy/status -> main.legacy_status"]["name"] == "legacy:legacy_status"
    for route in fixture_inventory["routes"]:
        assert route["permission_source"] == route["authentication_source"] == "dependency"
        assert route["actions"] == {}
        assert route["django_auth"] is None
        assert route["object_scoping"] is None


def test_t2_mounted_app_without_routes_is_one_dynamic_route(
    fixture_inventory: dict[str, Any],
) -> None:
    static = _routes(fixture_inventory)["any /static -> starlette.staticfiles.StaticFiles"]

    assert static["permission_classes"] == static["authentication_classes"] == "dynamic"


# T3 ---------------------------------------------------------------------------------------


def test_t3_dependencies_flattened_into_permission_classes(
    fixture_inventory: dict[str, Any],
) -> None:
    routes = _routes(fixture_inventory)

    assert routes["POST /items -> main.create_item"]["permission_classes"] == [
        "main.get_current_user",
        "main.get_db",
    ]
    # Router-level dependency of an outer router, nested dependency, parameter Depends.
    assert routes["GET /admin/reports/{report_id} -> main.get_report"]["permission_classes"] == [
        "main.get_current_user",
        "main.get_db",
        "main.require_admin",
    ]
    assert routes["GET /items -> main.list_items"]["permission_classes"] == ["main.CommonParams"]
    assert routes["DELETE /items/{item_id} -> main.delete_item"]["permission_classes"] == [
        "main.get_current_user[items:write]"
    ]


def get_user() -> None:
    """Load the user."""


def audit() -> None:
    return None


def test_t3_route_level_dependencies_scopes_and_deduplication() -> None:
    router = APIRouter(dependencies=[Depends(audit)])

    @router.get("/a", dependencies=[Depends(get_user)])
    def endpoint(
        first: None = Depends(get_user),
        second: None = Security(get_user, scopes=["write", "read", "write"]),
    ) -> None:
        return None

    app = FastAPI()
    app.include_router(router, prefix="/v1")

    [route] = [r for r in extract_app(app).routes if r.path == "/v1/a"]
    assert route.permission_classes == (
        f"{__name__}.audit",
        f"{__name__}.get_user",
        f"{__name__}.get_user[read,write]",
    )


# T4 ---------------------------------------------------------------------------------------


def test_t4_security_schemes_into_authentication_classes(
    fixture_inventory: dict[str, Any],
) -> None:
    routes = _routes(fixture_inventory)

    # OAuth2PasswordBearer is reached through get_current_user.
    assert routes["DELETE /items/{item_id} -> main.delete_item"]["authentication_classes"] == [
        OAUTH2
    ]
    assert routes["GET /token-info -> main.token_info"]["authentication_classes"] == [BEARER]
    assert routes["GET /token-info -> main.token_info"]["permission_classes"] == []
    assert routes["GET /items -> main.list_items"]["authentication_classes"] == []


class TenantKey(APIKeyHeader):
    """A project's own scheme class."""


def test_t4_scheme_subclass_is_recorded_by_its_own_path() -> None:
    app = FastAPI()

    @app.get("/k")
    def endpoint(key: str = Depends(TenantKey(name="X-Key"))) -> None:
        return None

    [route] = [r for r in extract_app(app).routes if r.path == "/k"]
    assert route.authentication_classes == (f"{__name__}.TenantKey",)
    assert route.permission_classes == ()


# T5 ---------------------------------------------------------------------------------------


def test_t5_exploding_dependency_never_called(fixture_inventory: dict[str, Any]) -> None:
    route = _routes(fixture_inventory)["GET,POST /search -> main.search"]

    assert route["permission_classes"] == ["main.Exploding"]


CALLS: list[str] = []


def guard() -> None:
    CALLS.append("guard")


class Checker:
    def __init__(self) -> None:
        CALLS.append("Checker")


def test_t5_no_dependency_or_endpoint_is_called_in_process() -> None:
    calls = CALLS
    calls.clear()
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(guard)])
    def endpoint(checker: Checker = Depends()) -> None:
        calls.append("endpoint")

    app.dependency_overrides[guard] = lambda: calls.append("override")

    [route] = [r for r in extract_app(app).routes if r.path == "/x"]
    assert calls == []
    # Overrides are a test-time setting and are not recorded.
    assert isinstance(route.permission_classes, tuple)
    assert not any("lambda" in entry for entry in route.permission_classes)


# T6 ---------------------------------------------------------------------------------------


def test_t6_registry_lists_dependencies_with_docstring_and_used_by(
    fixture_inventory: dict[str, Any],
) -> None:
    registry = fixture_inventory["custom_permissions"]

    assert sorted(registry) == [
        "main.CommonParams",
        "main.Exploding",
        "main.get_current_user",
        "main.get_db",
        "main.require_admin",
    ]
    assert registry["main.get_current_user"] == {
        "name": "get_current_user",
        "docstring": "Resolve the user the bearer token belongs to.",
        "used_by": [
            "DELETE /items/{item_id} -> main.delete_item",
            "GET /admin/reports/{report_id} -> main.get_report",
            "GET /admin/users -> main.list_users",
            "POST /items -> main.create_item",
        ],
    }
    assert registry["main.get_db"]["docstring"] is None
    assert registry["main.Exploding"]["name"] == "Exploding"
    assert not any(path.startswith(("fastapi.", "starlette.")) for path in registry)


# T8 ---------------------------------------------------------------------------------------


def _fastapi_route(permissions: Any, schemes: Any, methods: tuple[str, ...] = ("GET",)) -> Route:
    return Route(
        path="/r",
        name="r",
        view="main.r",
        methods=methods,
        permission_classes=permissions,
        permission_source="dependency",
        authentication_classes=schemes,
        authentication_source="dependency",
    )


def _label(base: Route, current: Route) -> tuple[str, str | None]:
    [entry] = classify_diff(compute(Inventory(routes=(base,)), Inventory(routes=(current,))))
    return entry.classification.label, entry.classification.rule


@pytest.mark.parametrize(
    ("old", "new", "label"),
    [
        (((), (OAUTH2,)), ((), ()), "loosened"),
        (((), ()), ((), (OAUTH2,)), "tightened"),
        (((), (OAUTH2,)), ((), (BEARER,)), "changed-unknown"),
        (((), (OAUTH2,)), ((), (OAUTH2, BEARER)), "changed-unknown"),
        ((("main.get_current_user",), (OAUTH2,)), ((), ()), "changed-unknown"),
        ((("main.get_current_user",), (OAUTH2,)), (("main.get_db",), (OAUTH2,)), "changed-unknown"),
        (((), (OAUTH2,)), ((), "dynamic"), "changed-unknown"),
    ],
)
def test_t8_r10_table(old: tuple[Any, Any], new: tuple[Any, Any], label: str) -> None:
    assert _label(_fastapi_route(*old), _fastapi_route(*new)) == (label, "R10")


def test_t8_r10_dependency_gained_is_not_r4_tightened() -> None:
    base = _fastapi_route(("main.get_db",), (OAUTH2,))
    current = _fastapi_route(("main.get_db", "main.require_admin"), (OAUTH2,))

    assert _label(base, current) == ("changed-unknown", "R10")


def test_t8_r10_other_changes_fall_through_to_r7() -> None:
    base = _fastapi_route((), (), methods=("GET",))
    current = _fastapi_route((), (), methods=("GET", "POST"))

    assert _label(base, current) == ("changed-unknown", "R7")


def test_t8_r10_dependency_sets_never_ranked() -> None:
    universe = [
        "main.get_current_user",
        "main.get_db",
        "main.require_admin",
        "main.get_current_user[items:write]",
        "rest_framework.permissions.IsAdminUser",
        "rest_framework.permissions.AllowAny",
    ]
    subsets = [
        tuple(sorted(combo))
        for size in range(len(universe) + 1)
        for combo in itertools.combinations(universe, size)
    ]
    checked = 0
    for old, new in itertools.product(subsets, repeat=2):
        if old == new:
            continue
        for schemes in ((), (OAUTH2,)):
            label, rule = _label(_fastapi_route(old, schemes), _fastapi_route(new, schemes))
            assert (label, rule) == ("changed-unknown", "R10"), (old, new, schemes)
            checked += 1
    assert checked > 8000


# T9 ---------------------------------------------------------------------------------------


def test_t9_each_framework_extracts_without_the_other(
    fixture_inventory: dict[str, Any],
) -> None:
    assert run_extract("fastapi_basic", block_modules=("django",)) == fixture_inventory
    assert run_extract("function_views", block_modules=("fastapi", "starlette")) == run_extract(
        "function_views"
    )


# T10 --------------------------------------------------------------------------------------


def _assert_two_line_error(result: Any, first: str) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""
    lines = result.stderr.rstrip("\n").split("\n")
    assert len(lines) == 2, result.stderr
    assert lines[0].startswith(f"authzlock: {first}"), result.stderr
    assert "Traceback" not in result.stderr


def test_t10_fastapi_missing_exits_2_with_two_lines() -> None:
    result = run_dump("fastapi_basic", block_modules=("fastapi",))

    _assert_two_line_error(result, "FastAPI is not installed.")


@pytest.mark.parametrize(
    ("app", "first"),
    [
        ("nonexistent_module:app", "App module 'nonexistent_module': cannot import"),
        ("main:missing", "App module 'main' has no attribute 'missing'."),
        ("main:oauth2_scheme", "main:oauth2_scheme is a OAuth2PasswordBearer, not a FastAPI"),
        (":app", "App ':app' names no module."),
    ],
)
def test_t10_loader_errors_exit_2_with_two_lines(app: str, first: str, tmp_path: Path) -> None:
    result = run_cli(
        ["update", "--app", app, "--lockfile", str(tmp_path / "authz.lock")],
        cwd=tmp_path,
        fixture="fastapi_basic",
    )

    _assert_two_line_error(result, first)
    assert not (tmp_path / "authz.lock").exists()


def test_t10_module_that_raises_on_import(tmp_path: Path) -> None:
    (tmp_path / "boom.py").write_text("raise RuntimeError('bad config')\n", encoding="utf-8")

    result = run_cli(["update", "--app", "boom"], cwd=tmp_path, env={"PYTHONPATH": str(tmp_path)})

    _assert_two_line_error(result, "App module 'boom' failed to import.")
    assert "RuntimeError: bad config" in result.stderr


def test_parse_app_defaults_attribute_to_app() -> None:
    assert parse_app("main") == ("main", "app")
    assert parse_app("pkg.api:application") == ("pkg.api", "application")
    with pytest.raises(ProjectLoadError):
        parse_app(":app")


def test_load_app_accepts_a_starlette_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "plain_starlette_app.py").write_text(
        "from starlette.applications import Starlette\napp = Starlette()\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert isinstance(load_app("plain_starlette_app"), Starlette)


# T12 --------------------------------------------------------------------------------------


def test_t12_sarif_locates_the_endpoint_of_a_changed_route(tmp_path: Path) -> None:
    repo = make_repo("fastapi_basic", tmp_path)
    main = repo / "main.py"
    _replace(
        main,
        "def create_item(user=Depends(get_current_user), db=Depends(get_db))",
        "def create_item(db=Depends(get_db))",
    )
    lines = main.read_text(encoding="utf-8").splitlines()
    decorator = lines.index("def create_item(db=Depends(get_db)) -> None:")

    result = run_cli(
        ["diff", "--base", "HEAD", "--format", "sarif"], cwd=repo, env=project_env(repo)
    )

    assert result.returncode == 1, result.stderr
    [run] = json.loads(result.stdout)["runs"]
    [finding] = run["results"]
    assert finding["ruleId"] == "changed-unknown"
    assert "POST /items -> main.create_item" in finding["message"]["text"]
    physical = finding["locations"][0]["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "main.py"
    # `inspect` starts a decorated function at its decorator, the line above the `def`.
    assert physical["region"] == {"startLine": decorator}


def test_t12_ignore_path_drops_a_fastapi_route_and_is_recorded(tmp_path: Path) -> None:
    repo = make_repo("fastapi_basic", tmp_path)

    result = run_cli(["update", "--ignore-path", "/admin"], cwd=repo, env=project_env(repo))
    check = run_cli(["check"], cwd=repo, env=project_env(repo))

    assert result.returncode == 0, result.stderr
    text = (repo / "authz.lock").read_text(encoding="utf-8")
    assert "ignore:\n  paths:\n  - /admin\n" in text
    assert "path: /admin" not in text
    assert "main.require_admin" not in text
    assert check.returncode == 0, check.stdout + check.stderr


# T13 --------------------------------------------------------------------------------------


def test_t13_gen_tests_refuses_a_fastapi_lockfile(tmp_path: Path, repo_root: Path) -> None:
    golden = repo_root / "tests" / "fixtures" / "fastapi_basic" / "authz.lock.expected"
    (tmp_path / "authz.lock").write_bytes(golden.read_bytes())

    result = run_cli(["gen-tests"], cwd=tmp_path)

    assert result.returncode == 2
    assert result.stderr == (
        "authzlock: authz.lock was written from a FastAPI app; "
        "gen-tests supports Django lockfiles only.\n"
    )
    assert not (tmp_path / "tests").exists()


# Extractor details ------------------------------------------------------------------------


def _decorated(function: Any) -> Any:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    return wrapper


class Service:
    def check(self) -> None:
        """Check the caller."""


def test_callable_path_names_functions_classes_methods_partials_and_instances() -> None:
    service = Service()

    assert callable_path(get_user) == (f"{__name__}.get_user", get_user)
    assert callable_path(Service)[0] == f"{__name__}.Service"
    assert callable_path(service.check)[0] == f"{__name__}.Service.check"
    assert callable_path(functools.partial(get_user))[0] == f"{__name__}.get_user"
    assert callable_path(_decorated(get_user))[0] == f"{__name__}.get_user"
    assert callable_path(OAuth2PasswordBearer(tokenUrl="t"))[0] == OAUTH2
    path, _ = callable_path(lambda: None)
    assert path.startswith(f"{__name__}.") and path.endswith(".<lambda>")


def test_docs_routes_are_recorded_without_dependencies() -> None:
    app = FastAPI()

    paths = {route.path: route for route in extract_app(app).routes}

    assert {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"} <= set(paths)
    assert paths["/openapi.json"].methods == ("GET",)
    assert paths["/openapi.json"].permission_classes == ()


def test_plain_starlette_routes_and_any_methods() -> None:
    from starlette.endpoints import HTTPEndpoint

    class Health(HTTPEndpoint):
        async def get(self, request: Any) -> None:
            return None

    app = Starlette(routes=[StarletteRoute("/health", Health)])

    [route] = extract_app(app).routes
    assert route.methods == ("any",)
    assert route.permission_classes == route.authentication_classes == ()


def test_fastapi_internals_the_extractor_reads_still_exist() -> None:
    from fastapi.routing import APIRoute

    app = FastAPI()

    @app.get("/x")
    def endpoint(user: None = Security(get_user, scopes=["s"])) -> None:
        return None

    [route] = [r for r in app.router.routes if isinstance(r, APIRoute)]
    [dependency] = route.dependant.dependencies
    assert dependency.call is get_user
    assert hasattr(dependency, "own_oauth_scopes") or hasattr(dependency, "security_scopes")


# T11 --------------------------------------------------------------------------------------


def test_t11_docs_and_readme_updated(repo_root: Path) -> None:
    from test_docs import cli_doc_drift, help_options

    options = help_options()
    for command in ("update", "check", "diff"):
        assert {"--app", "--framework"} <= options[command], command
    assert not {"--app", "--framework"} & options["gen-tests"]
    assert cli_doc_drift((repo_root / "docs" / "cli.md").read_text(encoding="utf-8")) == []

    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What authzlock does not do", 1)[1].split("\n## ", 1)[0]
    items = [line for line in section.splitlines() if line.startswith("- ")]
    assert len(items) == 3
    assert not any("does not support FastAPI" in item for item in items)
    assert "## FastAPI" in readme

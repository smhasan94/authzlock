"""Tests for SHA-244: `authzlock gen-tests` writes anonymous-access tests from the lockfile.

Planning, URL building and rendering are tested on hand-built routes. The generated module
is then run with pytest, in a subprocess, against copies of the fixture projects (T1, T9).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from authzlock.cli import app
from authzlock.errors import EXIT_ERROR, EXIT_OK
from authzlock.gen_tests import (
    REFUSED,
    REFUSED_OR_REDIRECT,
    build_url,
    generate,
    plan_route,
    summarize,
)
from authzlock.model import Route
from harness import FIXTURES, project_env, run_cli, run_generated_tests

PERMS = "rest_framework.permissions"
NO_AUTH: dict[str, Any] = {
    "login_required": False,
    "permission_required": [],
    "unknown_decorators": [],
    "user_passes_test": False,
}


def _drf(path: str, methods: tuple[str, ...], classes: Any) -> Route:
    return Route(
        path=path, name=None, view="api.views.V", methods=methods, permission_classes=classes
    )


def _django(path: str, methods: tuple[str, ...] = ("any",), **auth: Any) -> Route:
    return Route(
        path=path,
        name=None,
        view="shop.views.v",
        methods=methods,
        django_auth={**NO_AUTH, **auth},
    )


# Planning -----------------------------------------------------------------------------------


def test_t2_is_authenticated_asserts_every_method_401_or_403() -> None:
    for strongest in ("IsAuthenticated", "IsAdminUser"):
        route = _drf("orders/<int:pk>/", ("DELETE", "GET"), (f"{PERMS}.{strongest}",))

        plan = plan_route(route)

        assert plan.kind == "assert"
        assert plan.methods == ("DELETE", "GET")
        assert plan.accepted == REFUSED
        assert plan.url == "/orders/1/"

    text, _ = generate(
        [_drf("orders/<int:pk>/", ("DELETE", "GET"), (f"{PERMS}.IsAuthenticated",))],
        lockfile="authz.lock",
        output="tests/test_authz_lock.py",
    )
    assert '    ["DELETE", "GET"],\n' in text
    assert "        REFUSED,\n" in text
    assert "REFUSED = frozenset({401, 403})" in text


def test_t3_or_read_only_asserts_unsafe_methods_only() -> None:
    route = _drf("orders/", ("GET", "POST"), (f"{PERMS}.IsAuthenticatedOrReadOnly",))

    assert plan_route(route).methods == ("POST",)
    read_only = _drf("orders/", ("GET",), (f"{PERMS}.IsAuthenticatedOrReadOnly",))
    assert plan_route(read_only).kind == "none"


@pytest.mark.parametrize(
    ("classes", "named"),
    [
        (("api.permissions.IsOwner",), "api.permissions.IsOwner"),
        (
            (f"{PERMS}.IsAuthenticated", "api.permissions.IsOwner"),
            "api.permissions.IsOwner",
        ),
        (
            (f"({PERMS}.IsAuthenticated | api.permissions.IsOwner)",),
            f"({PERMS}.IsAuthenticated | api.permissions.IsOwner)",
        ),
        ("dynamic", "dynamic"),
    ],
)
def test_t4_custom_composed_and_dynamic_are_skipped_with_reason(classes: Any, named: str) -> None:
    plan = plan_route(_drf("x/", ("GET",), classes))

    assert plan.kind == "skip"
    assert named in plan.reason

    text, summary = generate([_drf("x/", ("GET",), classes)], lockfile="a.lock", output="t.py")
    assert summary.skipped == 1
    assert text.count("@pytest.mark.skip(") == 1


def test_t5_django_decorators_accept_302_and_user_passes_test_alone_is_skipped() -> None:
    login = plan_route(_django("members/", login_required=True))
    permission = plan_route(_django("reports/", ("GET", "POST"), permission_required=["a.b"]))
    passes_test = plan_route(_django("staff/", user_passes_test=True))
    both = plan_route(_django("both/", login_required=True, user_passes_test=True))

    assert (login.kind, login.methods, login.accepted) == ("assert", ("GET",), REFUSED_OR_REDIRECT)
    assert (permission.methods, permission.accepted) == (("GET", "POST"), REFUSED_OR_REDIRECT)
    assert passes_test.kind == "skip"
    assert "user_passes_test" in passes_test.reason
    assert both.kind == "assert"

    text, _ = generate([_django("members/", login_required=True)], lockfile="a", output="b")
    assert "REFUSED_OR_REDIRECT = frozenset({302, 401, 403})" in text
    assert "        REFUSED_OR_REDIRECT,\n" in text


def test_t6_open_routes_produce_no_test_and_are_counted() -> None:
    routes = [
        _drf("open/", ("GET", "POST"), (f"{PERMS}.AllowAny",)),
        _django("public/"),
        _django("cached/", unknown_decorators=["cache_page"]),
        Route(path="plain/", name=None, view="shop.views.plain", methods=("GET",)),
        _drf("closed/", ("GET",), (f"{PERMS}.IsAuthenticated",)),
    ]

    text, summary = generate(routes, lockfile="authz.lock", output="tests/test_authz_lock.py")

    counts = (summary.routes, summary.tests, summary.skipped, summary.without_assertions)
    assert counts == (5, 1, 0, 4)
    assert str(summary) == "5 routes, 1 tests, 0 skipped, 4 without assertions"
    assert len(re.findall(r"^def test_", text, re.MULTILINE)) == 1


@pytest.mark.parametrize(
    ("pattern", "url"),
    [
        ("orders/<int:pk>/", "/orders/1/"),
        ("posts/<slug:s>/", "/posts/s/"),
        ("files/<path:rest>", "/files/rest"),
        ("items/<pk>/", "/items/1/"),
        ("tokens/<uuid:u>/", "/tokens/00000000-0000-4000-8000-000000000001/"),
        ("^invoices/(?P<pk>[^/.]+)/$", "/invoices/1/"),
        ("^invoices/(?P<invoice_pk>[^/.]+)/lines/$", "/invoices/1/lines/"),
        ("^archive/(?P<year>[0-9]{4})/$", "/archive/2024/"),
        ("a/^legacy/(?P<sku>[0-9]+)/$", "/a/legacy/1/"),
        ("v2/^invoices/$", "/v2/invoices/"),
        ("", "/"),
        ("^invoices\\.(?P<format>[a-z0-9]+)/?$", None),
        ("^invoices/(?P<pk>[^/.]+)\\.(?P<format>[a-z0-9]+)/?$", None),
        ("<drf_format_suffix:format>", None),
        ("^code/(?P<c>[A-Z]{3})/$", None),
    ],
)
def test_t7_url_building_for_converters_router_regex_and_unbuildable_pattern(
    pattern: str, url: str | None
) -> None:
    assert build_url(pattern) == url


def test_t7_unbuildable_pattern_is_skipped_naming_it() -> None:
    pattern = "^invoices\\.(?P<format>[a-z0-9]+)/?$"

    plan = plan_route(_drf(pattern, ("GET",), (f"{PERMS}.IsAuthenticated",)))

    assert plan.kind == "skip"
    assert pattern in plan.reason


def test_extra_names_are_unique_and_valid_identifiers() -> None:
    routes = [
        _drf("x/", ("GET",), (f"{PERMS}.IsAuthenticated",)),
        _drf("x/", ("POST",), (f"{PERMS}.IsAuthenticated",)),
        _drf("", ("GET",), (f"{PERMS}.IsAuthenticated",)),
    ]

    text, _ = generate(routes, lockfile="a", output="b")

    names = re.findall(r"^def (test_\w*)\(", text, re.MULTILINE)
    assert names == ["test_x_v", "test_x_v_2", "test_v"]
    assert all(name.isidentifier() for name in names)


def test_extra_summary_counts_add_up() -> None:
    routes = [
        _drf("a/", ("GET",), (f"{PERMS}.IsAuthenticated",)),
        _drf("b/", ("GET",), "dynamic"),
        _drf("c/", ("GET",), (f"{PERMS}.AllowAny",)),
    ]

    summary = summarize([plan_route(route) for route in routes])

    assert summary.tests + summary.skipped + summary.without_assertions == summary.routes == 3


# The command --------------------------------------------------------------------------------


@pytest.fixture
def lockfile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`tmp_path` as the current directory, holding the drf_apiview golden lockfile."""
    shutil.copy(FIXTURES / "drf_apiview" / "authz.lock.expected", tmp_path / "authz.lock")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    return tmp_path


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(app, ["gen-tests", *args])


def test_t8_output_is_byte_stable_compiles_and_is_not_rewritten_when_unchanged(
    lockfile_dir: Path,
) -> None:
    output = lockfile_dir / "tests" / "test_authz_lock.py"

    first = _invoke()
    content = output.read_bytes()
    os.utime(output, (1_000_000_000, 1_000_000_000))
    second = _invoke()

    assert first.exit_code == second.exit_code == EXIT_OK, first.output + second.output
    assert first.stdout == (
        "tests/test_authz_lock.py: 15 routes, 5 tests, 6 skipped, 4 without assertions\n"
    )
    assert second.stdout.startswith("tests/test_authz_lock.py: unchanged (")
    assert output.read_bytes() == content
    assert output.stat().st_mtime == 1_000_000_000
    compile(content, str(output), "exec")
    assert not re.search(rb"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", content)


def test_extra_generated_module_passes_ruff_check_and_format(lockfile_dir: Path) -> None:
    for fixture in ("drf_apiview", "drf_viewsets", "function_views", "class_views"):
        shutil.copy(FIXTURES / fixture / "authz.lock.expected", lockfile_dir / f"{fixture}.lock")
        result = _invoke("--lockfile", f"{fixture}.lock", "--output", f"out/test_{fixture}.py")
        assert result.exit_code == EXIT_OK, result.output

    for command in (["check"], ["format", "--check"]):
        ruff = subprocess.run(
            [sys.executable, "-m", "ruff", *command, "--isolated", "out"],
            cwd=lockfile_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ruff.returncode == 0, ruff.stdout + ruff.stderr


def test_t10_missing_lockfile_exits_2_and_output_parent_is_created(lockfile_dir: Path) -> None:
    missing = _invoke("--lockfile", "nope.lock")
    nested = _invoke("--output", "a/b/c/test_generated.py")
    (lockfile_dir / "taken").write_text("a file, not a directory\n", encoding="utf-8")
    unwritable = _invoke("--output", "taken/test_generated.py")

    assert missing.exit_code == EXIT_ERROR
    assert "nope.lock not found" in missing.stderr
    assert "authzlock update" in missing.stderr
    assert nested.exit_code == EXIT_OK, nested.output
    assert (lockfile_dir / "a" / "b" / "c" / "test_generated.py").is_file()
    assert unwritable.exit_code == EXIT_ERROR
    assert unwritable.stderr.startswith("authzlock: cannot write taken/test_generated.py")
    assert "pass --output with another path" in unwritable.stderr


def test_extra_invalid_lockfile_exits_2(lockfile_dir: Path) -> None:
    (lockfile_dir / "authz.lock").write_text("schema_version: 99\nroutes: []\n", encoding="utf-8")

    result = _invoke()

    assert result.exit_code == EXIT_ERROR
    assert "schema_version" in result.stderr


def test_extra_generation_never_sets_up_django(lockfile_dir: Path) -> None:
    script = (
        "from typer.testing import CliRunner\n"
        "from authzlock.cli import app\n"
        "result = CliRunner().invoke(app, ['gen-tests'])\n"
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        "print(result.exit_code, apps.ready, settings.configured)\n"
    )
    env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=lockfile_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.stdout.split() == ["0", "False", "False"], result.stdout + result.stderr


# Running the generated module ---------------------------------------------------------------


def _project(fixture: str, tmp_path: Path) -> Path:
    """A copy of `fixture` with a lockfile written by `update` for the installed versions."""
    project = tmp_path / fixture
    shutil.copytree(
        FIXTURES / fixture, project, ignore=shutil.ignore_patterns("*.expected", "__pycache__")
    )
    result = run_cli(["update", "--quiet"], cwd=project, env=project_env(project))
    assert result.returncode == EXIT_OK, result.stderr
    return project


def _generate(project: Path) -> Path:
    result = run_cli(["gen-tests"], cwd=project, env=project_env(project))
    assert result.returncode == EXIT_OK, result.stderr
    return project / "tests" / "test_authz_lock.py"


@pytest.mark.parametrize("fixture", ["function_views", "drf_viewsets"])
def test_t1_generated_module_passes_against_fixture(fixture: str, tmp_path: Path) -> None:
    project = _project(fixture, tmp_path)
    module = _generate(project)

    result = run_generated_tests(project, module)

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\d+ passed", result.stdout), result.stdout
    assert "failed" not in result.stdout


def test_t9_loosening_to_allow_any_makes_generated_test_fail(tmp_path: Path) -> None:
    project = _project("drf_apiview", tmp_path)
    module = _generate(project)
    before = run_generated_tests(project, module, select="explicit")
    assert before.returncode == 0, before.stdout + before.stderr

    views = project / "api" / "views.py"
    text = views.read_text(encoding="utf-8")
    old = "class ExplicitView(APIView):\n    permission_classes = [IsAuthenticated]\n"
    assert text.count(old) == 1
    views.write_text(
        "from rest_framework.permissions import AllowAny\n"
        + text.replace(old, old.replace("IsAuthenticated]", "AllowAny]")),
        encoding="utf-8",
    )

    after = run_generated_tests(project, module, select="explicit")

    assert after.returncode == 1, after.stdout + after.stderr
    assert "1 failed" in after.stdout
    assert "GET explicit/ -> api.views.ExplicitView is expected to refuse it" in after.stdout

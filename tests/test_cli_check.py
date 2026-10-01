"""Tests for SHA-226: `authzlock check`.

Every test that loads a fixture project runs the CLI in a subprocess (`run_cli`), because
Django can only be set up once per process. T4 and T5 run in-process: `check` reads the
lockfile before it loads the project, so they fail before Django is imported. The
`render_check` tests use hand-built inventories and never load a project.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from authzlock.cli import app
from authzlock.diff import compute
from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK
from authzlock.model import Inventory, Route
from authzlock.render import render_check
from harness import run_cli

FIXTURE = "drf_viewsets"
HINT = "run `authzlock update` and commit authz.lock"
SUMMARY_PATH = "^invoices/summary/$"
SUMMARY_KEY = "GET ^invoices/summary/$ -> billing.views.InvoiceViewSet"
IS_AUTHENTICATED = "rest_framework.permissions.IsAuthenticated"
ALLOW_ANY = "rest_framework.permissions.AllowAny"


def _update(tmp_path: Path) -> Path:
    """Run `authzlock update` for the fixture in `tmp_path` and return the lockfile path."""
    result = run_cli(["update"], cwd=tmp_path, fixture=FIXTURE)
    assert result.returncode == EXIT_OK, result.stderr
    return tmp_path / "authz.lock"


def _edit(path: Path, change: Any) -> None:
    """Apply `change` to the parsed lockfile document and write it back."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _summary_route(data: dict[str, Any]) -> dict[str, Any]:
    routes = [route for route in data["routes"] if route["path"] == SUMMARY_PATH]
    assert len(routes) == 1
    route: dict[str, Any] = routes[0]
    return route


def _section(output: str, header: str) -> list[str]:
    """The indented lines that follow the `header:` line, up to the next unindented line."""
    lines = output.splitlines()
    assert f"{header}:" in lines, output
    start = lines.index(f"{header}:") + 1
    section: list[str] = []
    for line in lines[start:]:
        if not line.startswith(" "):
            break
        section.append(line)
    return section


def _check(tmp_path: Path) -> Any:
    return run_cli(["check"], cwd=tmp_path, fixture=FIXTURE)


def test_t1_check_up_to_date_exits_0(tmp_path: Path) -> None:
    _update(tmp_path)

    result = _check(tmp_path)

    assert result.returncode == EXIT_OK, result.stderr
    assert result.stdout == "authz.lock: up to date\n"
    assert result.stderr == ""


def test_t2_route_missing_from_lockfile_is_reported_added(tmp_path: Path) -> None:
    path = _update(tmp_path)
    _edit(path, lambda data: data["routes"].remove(_summary_route(data)))
    before = path.read_bytes()

    result = _check(tmp_path)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert _section(result.stdout, "added") == [f"  {SUMMARY_KEY}"]
    assert "removed:" not in result.stdout
    assert "changed:" not in result.stdout
    assert HINT in result.stdout
    assert path.read_bytes() == before


def test_t3_changed_permission_classes_shown_old_to_new(tmp_path: Path) -> None:
    path = _update(tmp_path)

    def loosen(data: dict[str, Any]) -> None:
        _summary_route(data)["permission_classes"] = [ALLOW_ANY]

    _edit(path, loosen)

    result = _check(tmp_path)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert _section(result.stdout, "changed") == [
        f"  {SUMMARY_KEY}",
        f"    permission_classes: [{ALLOW_ANY}] -> [{IS_AUTHENTICATED}]",
    ]
    assert "added:" not in result.stdout
    assert HINT in result.stdout


def test_t4_missing_lockfile_exits_2_with_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["check"], env={"DJANGO_SETTINGS_MODULE": None})

    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stderr.startswith("authzlock: ")
    assert "authz.lock" in result.stderr
    assert "not found" in result.stderr
    assert "authzlock update" in result.stderr
    assert len(result.stderr.strip().splitlines()) <= 2
    assert result.stdout == ""
    assert not (tmp_path / "authz.lock").exists()


def test_t5_newer_schema_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "authz.lock").write_text("schema_version: 99\nroutes: []\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["check"], env={"DJANGO_SETTINGS_MODULE": None})

    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stderr.startswith("authzlock: ")
    assert "newer" in result.stderr
    assert "schema_version 99" in result.stderr
    assert len(result.stderr.strip().splitlines()) <= 2
    assert result.stdout == ""


def _reformat(text: str) -> str:
    """Add blank lines between routes and quote every view name and class path."""
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("- path:"):
            out.extend(["", ""])
        line = re.sub(r"^(  view: )(\S+)$", r"\1'\2'", line)
        line = re.sub(r"^(  - )(rest_framework\.\S+)$", r'\1"\2"', line)
        out.append(line)
    return "\n".join(out) + "\n\n\n"


def test_t6_formatting_only_differences_pass(tmp_path: Path) -> None:
    path = _update(tmp_path)
    original = path.read_text(encoding="utf-8")
    reformatted = _reformat(original)
    assert reformatted != original
    assert "\n\n- path:" in reformatted
    assert "  view: 'billing.views.InvoiceViewSet'" in reformatted
    assert f'  - "{IS_AUTHENTICATED}"' in reformatted
    path.write_text(reformatted, encoding="utf-8")

    result = _check(tmp_path)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert result.stdout == "authz.lock: up to date\n"
    assert path.read_text(encoding="utf-8") == reformatted


def test_t7_extra_route_in_lockfile_is_reported_removed(tmp_path: Path) -> None:
    path = _update(tmp_path)

    def add_bogus(data: dict[str, Any]) -> None:
        bogus = dict(
            _summary_route(data), path="^bogus/$", name="bogus", view="billing.views.Bogus"
        )
        data["routes"].append(bogus)

    _edit(path, add_bogus)

    result = _check(tmp_path)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert _section(result.stdout, "removed") == ["  GET ^bogus/$ -> billing.views.Bogus"]
    assert "added:" not in result.stdout
    assert HINT in result.stdout


def test_extra_quiet_up_to_date_prints_nothing(tmp_path: Path) -> None:
    _update(tmp_path)

    result = run_cli(["check", "--quiet"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_OK, result.stderr
    assert result.stdout == ""


def test_extra_quiet_still_reports_a_mismatch(tmp_path: Path) -> None:
    path = _update(tmp_path)
    _edit(path, lambda data: data["routes"].remove(_summary_route(data)))

    result = run_cli(["check", "-q"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert SUMMARY_KEY in result.stdout


def test_extra_lockfile_option_names_the_path_in_the_hint(tmp_path: Path) -> None:
    update = run_cli(["update", "--lockfile", "locks/authz.lock"], cwd=tmp_path, fixture=FIXTURE)
    assert update.returncode == EXIT_OK, update.stderr
    _edit(tmp_path / "locks" / "authz.lock", lambda d: d["routes"].remove(_summary_route(d)))

    result = run_cli(["check", "--lockfile", "locks/authz.lock"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert "run `authzlock update` and commit locks/authz.lock" in result.stdout


def test_extra_project_load_failure_exits_2(tmp_path: Path) -> None:
    (tmp_path / "authz.lock").write_text("schema_version: 1\nroutes: []\n", encoding="utf-8")

    result = run_cli(["check"], cwd=tmp_path, fixture="broken")

    assert result.returncode == EXIT_ERROR, result.stdout
    assert "boom" in result.stderr
    assert "Traceback" not in result.stderr


def test_extra_invalid_lockfile_names_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "authz.lock").write_text("routes: [\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["check"], env={"DJANGO_SETTINGS_MODULE": None})

    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stderr.startswith("authzlock: authz.lock: ")
    assert "not valid YAML" in result.stderr


# render_check on hand-built inventories.

ORDERS = Route(
    path="api/orders/",
    name="order-list",
    view="api.views.OrderViewSet",
    methods=("GET", "POST"),
    actions={"GET": "list", "POST": "create"},
    permission_classes=(IS_AUTHENTICATED,),
    permission_source="view",
    object_scoping={"get_queryset": {"overridden": True, "references_request_user": True}},
)
MEMBERS = Route(path="members/", name=None, view="shop.views.members", methods=("any",))
REPORTS = Route(path="reports/", name="reports", view="shop.views.reports", methods=("GET",))


def test_extra_render_check_groups_routes_and_fields() -> None:
    changed = Route(
        path="api/orders/",
        name="order-list",
        view="api.views.OrderViewSet",
        methods=("GET", "POST"),
        actions={"GET": "list", "POST": "create"},
        permission_classes="dynamic",
        permission_source=None,
        object_scoping={"get_queryset": {"overridden": True, "references_request_user": False}},
    )
    diff = compute(
        Inventory(routes=(ORDERS, MEMBERS)),
        Inventory(routes=(changed, REPORTS)),
    )

    assert render_check(diff) == (
        "authz.lock is out of date.\n"
        "added:\n"
        "  GET reports/ -> shop.views.reports\n"
        "removed:\n"
        "  any members/ -> shop.views.members\n"
        "changed:\n"
        "  GET,POST api/orders/ -> api.views.OrderViewSet\n"
        f"    permission_classes: [{IS_AUTHENTICATED}] -> dynamic\n"
        "    permission_source: view -> null\n"
        "    object_scoping.get_queryset.references_request_user: true -> false\n"
        "\n"
        f"To fix: {HINT}.\n"
    )


def test_extra_render_check_reports_registry_changes() -> None:
    base = {
        "app.perms.IsOwner": {"name": "IsOwner", "docstring": "Owner only.", "used_by": []},
        "app.perms.Old": {"name": "Old", "docstring": None, "used_by": []},
    }
    current = {
        "app.perms.IsOwner": {
            "name": "IsOwner",
            "docstring": "Owner only.\nStaff too.",
            "used_by": ["GET reports/ -> shop.views.reports"],
        },
        "app.perms.New": {"name": "New", "docstring": None, "used_by": []},
    }
    diff = compute(
        Inventory(routes=(REPORTS,), custom_permissions=base),
        Inventory(routes=(REPORTS,), custom_permissions=current),
    )

    assert render_check(diff, lockfile="locks/authz.lock") == (
        "locks/authz.lock is out of date.\n"
        "custom permissions added:\n"
        "  app.perms.New\n"
        "custom permissions removed:\n"
        "  app.perms.Old\n"
        "custom permissions changed:\n"
        "  app.perms.IsOwner\n"
        '    docstring: Owner only. -> "Owner only.\\nStaff too."\n'
        "    used_by: [] -> [GET reports/ -> shop.views.reports]\n"
        "\n"
        "To fix: run `authzlock update` and commit locks/authz.lock.\n"
    )


def test_extra_render_check_formats_mappings_and_empty_values() -> None:
    changed = dataclasses.replace(
        ORDERS, actions={"POST": "create", "GET": "list", "PUT": "update"}, permission_classes=()
    )
    diff = compute(Inventory(routes=(ORDERS,)), Inventory(routes=(changed,)))

    assert _section(render_check(diff), "changed") == [
        "  GET,POST api/orders/ -> api.views.OrderViewSet",
        "    actions: {GET: list, POST: create} -> {GET: list, POST: create, PUT: update}",
        f"    permission_classes: [{IS_AUTHENTICATED}] -> []",
    ]

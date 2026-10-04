"""Tests for SHA-230: `authzlock diff --base <ref>`.

Every test that loads a project builds a temporary git repository from a fixture with
`make_repo`, edits the working tree, and runs the CLI in a subprocess (`run_cli`) with that
copy on `PYTHONPATH`, because Django can only be set up once per process. T5, T7 and the
other error cases run in-process: `diff` reads git and the base lockfile before it loads
the project, so they fail before Django is imported. The renderer tests use hand-built
inventories and never load a project.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from authzlock.cli import app
from authzlock.diff import compute
from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK
from authzlock.model import Inventory, Route
from authzlock.render import build_report, render_markdown, render_text
from harness import GIT_ENV, git, init_repo, make_repo, project_env, run_cli

FIXTURE = "drf_apiview"
DETAIL_KEY = "DELETE,GET orders/<int:pk>/ -> api.views.OrderDetailView"
EXPLICIT_KEY = "GET explicit/ -> api.views.ExplicitView"
IS_OWNER = "api.permissions.IsOwner"
IS_AUTHENTICATED = "rest_framework.permissions.IsAuthenticated"
IS_ADMIN_USER = "rest_framework.permissions.IsAdminUser"
ALLOW_ANY = "rest_framework.permissions.AllowAny"
SUMMARY = re.compile(
    r"^(\d+) loosened, (\d+) tightened, (\d+) added, (\d+) removed, (\d+) changed-unknown$",
    re.MULTILINE,
)
NO_LOCKFILE_NOTE = "base ref has no authz.lock"


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} not found exactly once in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _loosen_order_detail(repo: Path) -> None:
    """[IsOwner] -> [IsAuthenticated] on OrderDetailView: R2, loosened."""
    _replace(
        repo / "api" / "views.py",
        "class OrderDetailView(generics.RetrieveDestroyAPIView):\n"
        "    permission_classes = [IsOwner]\n",
        "class OrderDetailView(generics.RetrieveDestroyAPIView):\n"
        "    permission_classes = [IsAuthenticated]\n",
    )


def _tighten_explicit(repo: Path) -> None:
    """[IsAuthenticated] -> [IsAdminUser] on ExplicitView: R1, tightened."""
    _replace(
        repo / "api" / "views.py",
        "class ExplicitView(APIView):\n    permission_classes = [IsAuthenticated]\n",
        "class ExplicitView(APIView):\n    permission_classes = [IsAdminUser]\n",
    )


def _diff(repo: Path, *args: str, cwd: Path | None = None) -> Any:
    return run_cli(["diff", "--base", "HEAD", *args], cwd=cwd or repo, env=project_env(repo))


def _summary(output: str) -> tuple[int, ...]:
    matches = SUMMARY.findall(output)
    assert len(matches) == 1, output
    return tuple(int(count) for count in matches[0])


def _lines_starting(output: str, label: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(label)]


# Integration ------------------------------------------------------------------------------


def test_t1_no_changes_exits_0(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)

    result = _diff(repo)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert result.stdout == "no changes\n"
    assert result.stderr == ""


def test_t2_loosened_line_names_methods_path_view(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    _loosen_order_detail(repo)

    result = _diff(repo)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    lines = _lines_starting(result.stdout, "loosened")
    assert len(lines) == 1, result.stdout
    line = lines[0]
    assert DETAIL_KEY in line
    assert f"permission_classes: [{IS_OWNER}] -> [{IS_AUTHENTICATED}]" in line
    assert "R2" in line
    assert _summary(result.stdout) == (1, 0, 0, 0, 0)
    # The lockfile in the working tree is neither read nor written.
    assert git(repo, "status", "--porcelain") == " M api/views.py\n"


def test_t3_markdown_summary_and_row(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    _loosen_order_detail(repo)

    result = _diff(repo, "--format", "markdown")

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert _summary(result.stdout) == (1, 0, 0, 0, 0)
    assert "1 loosened" in result.stdout
    rows = [line for line in result.stdout.splitlines() if line.startswith("| loosened |")]
    assert len(rows) == 1, result.stdout
    row = rows[0]
    assert "DELETE,GET" in row
    assert "`orders/<int:pk>/`" in row
    assert "`api.views.OrderDetailView`" in row
    assert "R2" in row
    assert f"`[{IS_OWNER}]` → `[{IS_AUTHENTICATED}]`" in row


def test_t4_base_without_lockfile_reports_all_added_with_note(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile=None)
    current = run_cli(["update", "--lockfile", "../current.lock"], cwd=repo, env=project_env(repo))
    assert current.returncode == EXIT_OK, current.stderr
    route_count = (tmp_path / "current.lock").read_text(encoding="utf-8").count("\n- path:")
    assert route_count > 5

    result = _diff(repo)

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert NO_LOCKFILE_NOTE in result.stdout
    added = _lines_starting(result.stdout, "added")
    assert len(added) == route_count
    assert any(DETAIL_KEY in line for line in added)
    for label in ("loosened", "tightened", "removed", "changed-unknown"):
        assert not _lines_starting(result.stdout, label), result.stdout
    assert _summary(result.stdout) == (0, 0, route_count, 0, 0)

    markdown = _diff(repo, "--format", "markdown")
    assert markdown.returncode == EXIT_MISMATCH, markdown.stderr
    assert NO_LOCKFILE_NOTE in markdown.stdout


def test_t6_fail_on_loosened_ignores_tightened(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    _tighten_explicit(repo)

    result = _diff(repo, "--fail-on", "loosened")

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    tightened = _lines_starting(result.stdout, "tightened")
    assert len(tightened) == 1 and EXPLICIT_KEY in tightened[0], result.stdout
    assert _summary(result.stdout) == (0, 1, 0, 0, 0)
    # Without the option any change fails.
    assert _diff(repo).returncode == EXIT_MISMATCH


def test_t8_lockfile_in_subdirectory_uses_repo_relative_path(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile="sub/authz.lock")
    assert not (repo / "authz.lock").exists()
    _loosen_order_detail(repo)

    result = _diff(repo, "--lockfile", "sub/authz.lock")

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert NO_LOCKFILE_NOTE not in result.stdout
    lines = _lines_starting(result.stdout, "loosened")
    assert len(lines) == 1 and DETAIL_KEY in lines[0], result.stdout
    assert _summary(result.stdout) == (1, 0, 0, 0, 0)


def test_extra_run_from_subdirectory_resolves_lockfile_against_repo_root(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile="sub/authz.lock")
    _loosen_order_detail(repo)

    result = _diff(repo, "--lockfile", "authz.lock", cwd=repo / "sub")

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert NO_LOCKFILE_NOTE not in result.stdout
    assert _summary(result.stdout) == (1, 0, 0, 0, 0)


def test_extra_fail_on_loosened_still_fails_on_loosened(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    _loosen_order_detail(repo)
    _tighten_explicit(repo)

    result = _diff(repo, "--fail-on", "loosened", "--format", "markdown")

    assert result.returncode == EXIT_MISMATCH, result.stderr
    assert _summary(result.stdout) == (1, 1, 0, 0, 0)


def test_extra_markdown_contains_marker(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)

    clean = _diff(repo, "--format", "markdown")
    _loosen_order_detail(repo)
    changed = _diff(repo, "--format", "markdown")

    assert clean.returncode == EXIT_OK, clean.stderr
    assert clean.stdout.startswith("<!-- authzlock -->\n")
    assert "No access-control changes" in clean.stdout
    assert _summary(clean.stdout) == (0, 0, 0, 0, 0)
    assert changed.stdout.startswith("<!-- authzlock -->\n")


def test_extra_quiet_prints_nothing_without_changes(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)

    result = _diff(repo, "--quiet")

    assert result.returncode == EXIT_OK, result.stderr
    assert result.stdout == ""


# In-process error cases -------------------------------------------------------------------


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in `tmp_path` with the test git environment; git never looks above it."""
    for key, value in GIT_ENV.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(app, ["diff", *args])


def _assert_error(result: Any) -> None:
    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stderr.startswith("authzlock: ")
    assert len(result.stderr.strip().splitlines()) <= 2, result.stderr
    assert result.stdout == ""


def test_t5_unknown_ref_exits_2_with_git_error(isolated_git: Path) -> None:
    init_repo(isolated_git)

    result = _invoke("--base", "nope")

    _assert_error(result)
    assert "nope" in result.stderr
    assert "fatal:" in result.stderr


def test_t7_outside_git_repo_exits_2(isolated_git: Path) -> None:
    result = _invoke("--base", "main")

    _assert_error(result)
    assert "not a git repository" in result.stderr


def test_extra_ref_starting_with_dash_is_refused(isolated_git: Path) -> None:
    init_repo(isolated_git)

    result = _invoke("--base=--output=x")

    _assert_error(result)
    assert "--output=x" in result.stderr
    assert not (isolated_git / "x").exists()


def test_extra_lockfile_outside_repo_exits_2(
    isolated_git: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(init_repo(isolated_git / "repo"))
    (isolated_git / "elsewhere").mkdir()

    result = CliRunner().invoke(
        app, ["diff", "--base", "HEAD", "--lockfile", str(isolated_git / "elsewhere/authz.lock")]
    )

    _assert_error(result)
    assert "outside" in result.stderr


def test_extra_unreadable_base_lockfile_exits_2(isolated_git: Path) -> None:
    init_repo(isolated_git)
    (isolated_git / "authz.lock").write_text("schema_version: 99\nroutes: []\n", encoding="utf-8")
    git(isolated_git, "add", "authz.lock")
    git(isolated_git, "commit", "--quiet", "--message", "future lockfile")

    result = _invoke("--base", "HEAD")

    _assert_error(result)
    assert "HEAD:authz.lock" in result.stderr
    assert "schema_version 99" in result.stderr


def test_extra_unknown_format_is_a_usage_error(isolated_git: Path) -> None:
    result = _invoke("--base", "HEAD", "--format", "xml")

    assert result.exit_code == EXIT_ERROR
    assert "xml" in result.stderr


# Renderers --------------------------------------------------------------------------------


def _route(
    path: str, view: str, permission_classes: Any, methods: tuple[str, ...] = ("GET",)
) -> Route:
    return Route(
        path=path,
        name=None,
        view=view,
        methods=methods,
        permission_classes=permission_classes,
        permission_source="view",
    )


def _report(base: Inventory, current: Inventory, *, base_found: bool = True) -> Any:
    return build_report(
        compute(base, current), ref="origin/main", lockfile="authz.lock", base_found=base_found
    )


BASE = Inventory(
    routes=(
        _route("a/", "app.views.A", (IS_OWNER,)),
        _route("b/", "app.views.B", (IS_AUTHENTICATED,)),
        _route("c/", "app.views.C", "dynamic"),
        _route("gone/", "app.views.Gone", (IS_AUTHENTICATED,)),
        _route("same/", "app.views.Same", (IS_AUTHENTICATED,)),
    )
)
CURRENT = Inventory(
    routes=(
        _route("a/", "app.views.A", (IS_AUTHENTICATED,)),
        _route("b/", "app.views.B", (IS_ADMIN_USER,)),
        _route("c/", "app.views.C", (IS_AUTHENTICATED,)),
        _route("new/(a|b)/", "app.views.New", (ALLOW_ANY,), ("GET", "POST")),
        _route("same/", "app.views.Same", (IS_AUTHENTICATED,)),
    )
)


def test_extra_render_text_groups_in_summary_order() -> None:
    text = render_text(_report(BASE, CURRENT))

    labels = [line.split()[0] for line in text.splitlines() if line and line[0].islower()]
    assert labels == ["loosened", "tightened", "added", "removed", "changed-unknown"]
    assert text.splitlines()[-1] == "1 loosened, 1 tightened, 1 added, 1 removed, 1 changed-unknown"
    added = _lines_starting(text, "added")
    assert added == [
        f"added           GET,POST new/(a|b)/ -> app.views.New  permission_classes: [{ALLOW_ANY}]"
    ]
    removed = _lines_starting(text, "removed")
    assert removed == [
        f"removed         GET gone/ -> app.views.Gone  permission_classes: [{IS_AUTHENTICATED}]"
    ]
    unknown = _lines_starting(text, "changed-unknown")
    assert unknown[0].startswith("changed-unknown GET c/ -> app.views.C  permission_classes: ")
    assert "(R5:" in unknown[0]


def test_extra_render_text_empty_diff() -> None:
    assert render_text(_report(BASE, BASE)) == "no changes\n"
    assert render_text(_report(Inventory(), Inventory(), base_found=False)).startswith(
        "note: base ref has no authz.lock"
    )


def test_extra_render_markdown_tables_details_and_escaping() -> None:
    markdown = render_markdown(_report(BASE, CURRENT))

    lines = markdown.splitlines()
    assert lines[0] == "<!-- authzlock -->"
    assert "1 loosened, 1 tightened, 1 added, 1 removed, 1 changed-unknown" in lines
    # Loosened and tightened are in the open table, the rest in collapsed sections.
    open_part, _, collapsed = markdown.partition("<details>")
    assert "| loosened |" in open_part and "| tightened |" in open_part
    assert "| added |" not in open_part and "| changed-unknown |" not in open_part
    assert "| added |" in collapsed and "| removed |" in collapsed
    assert "| changed-unknown |" in collapsed
    assert collapsed.count("<details>") == 2 and markdown.count("</details>") == 3
    # A pipe in a path must not split the table cell.
    assert "`new/(a\\|b)/`" in markdown
    for line in lines:
        if line.startswith("| added |"):
            assert len(re.findall(r"(?<!\\)\|", line)) == 6, line


def test_extra_render_includes_custom_permission_changes() -> None:
    base = Inventory(custom_permissions={IS_OWNER: {"name": "IsOwner", "docstring": "Old."}})
    current = Inventory(custom_permissions={IS_OWNER: {"name": "IsOwner", "docstring": "New."}})
    report = _report(base, current)

    text = render_text(report)
    markdown = render_markdown(report)

    assert f"custom-permission changed {IS_OWNER}  docstring: Old. -> New." in text
    assert "0 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown" in text
    assert IS_OWNER in markdown and "No access-control changes" not in markdown

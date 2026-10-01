"""Tests for SHA-231: the MVP success scenario, IsOwner dropped from a DELETE endpoint.

Each test copies `tests/fixtures/scenario_loosen` into a temporary git repository with
`make_repo` (fixture and lockfile committed), edits `billing/views.py` the way a pull request
would, and runs the CLI in a subprocess (`run_cli`), because Django can only be set up once
per process. T6 keeps the output shown in `docs/scenario.md` equal to the real output; run
`pytest tests/test_scenario.py --update-docs` to rewrite it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from authzlock.errors import EXIT_MISMATCH, EXIT_OK
from harness import git, make_repo, project_env, run_cli

FIXTURE = "scenario_loosen"
VIEWS = Path("billing") / "views.py"
ROUTE_KEY = "DELETE,GET invoices/<int:pk>/ -> billing.views.InvoiceDetailView"
IS_OWNER = "billing.permissions.IsOwner"
IS_TENANT_ADMIN = "billing.permissions.IsTenantAdmin"
IS_AUTHENTICATED = "rest_framework.permissions.IsAuthenticated"
ORIGINAL = "    permission_classes = [IsAuthenticated, IsOwner]\n"
LOOSENED = "    permission_classes = [IsAuthenticated]\n"
SUMMARY = re.compile(
    r"^(\d+) loosened, (\d+) tightened, (\d+) added, (\d+) removed, (\d+) changed-unknown$",
    re.MULTILINE,
)
DOC = Path(__file__).resolve().parent.parent / "docs" / "scenario.md"


def _replace(repo: Path, old: str, new: str) -> None:
    path = repo / VIEWS
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} not found exactly once in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _loosen(repo: Path) -> None:
    """The pull request of the scenario: `IsOwner` removed, `IsAuthenticated` left."""
    _replace(repo, ORIGINAL, LOOSENED)


def _cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_cli(args, cwd=repo, env=project_env(repo))


def _diff(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _cli(repo, "diff", "--base", "HEAD", *args)


def _update_and_commit(repo: Path, message: str) -> None:
    result = _cli(repo, "update")
    assert result.returncode == EXIT_OK, result.stderr
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", message)


def _summary(output: str) -> tuple[int, ...]:
    matches = SUMMARY.findall(output)
    assert len(matches) == 1, output
    return tuple(int(count) for count in matches[0])


def _rows(markdown: str, label: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith(f"| {label} |")]


@pytest.fixture
def loosened_repo(tmp_path: Path) -> Path:
    """The scenario repository with the loosening edit applied but not committed."""
    repo = make_repo(FIXTURE, tmp_path)
    _loosen(repo)
    return repo


def test_t1_loosening_patch_yields_loosened_row_with_r2(loosened_repo: Path) -> None:
    result = _diff(loosened_repo, "--format", "markdown")

    assert result.returncode == EXIT_MISMATCH, result.stdout + result.stderr
    assert result.stdout.startswith("<!-- authzlock -->\n")
    assert _summary(result.stdout) == (1, 0, 0, 0, 0)
    rows = _rows(result.stdout, "loosened")
    assert len(rows) == 1, result.stdout
    row = rows[0]
    assert "| DELETE,GET |" in row
    assert "`invoices/<int:pk>/`" in row
    assert "`billing.views.InvoiceDetailView`" in row
    assert f"`R2: custom class {IS_OWNER} removed`" in row
    assert f"`[{IS_OWNER}, {IS_AUTHENTICATED}]` → `[{IS_AUTHENTICATED}]`" in row
    # The default --fail-on any and the Action's --fail-on loosened both fail the run.
    assert _diff(loosened_repo, "--fail-on", "loosened").returncode == EXIT_MISMATCH


def test_t2_check_fails_after_patch(loosened_repo: Path) -> None:
    result = _cli(loosened_repo, "check")

    assert result.returncode == EXIT_MISMATCH, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "authz.lock is out of date." in output
    lines = output.splitlines()
    index = lines.index("changed:")
    assert lines[index + 1] == f"  {ROUTE_KEY}"
    assert (
        f"    permission_classes: [{IS_OWNER}, {IS_AUTHENTICATED}] -> [{IS_AUTHENTICATED}]" in lines
    )
    assert "To fix: run `authzlock update` and commit authz.lock." in output


def test_t3_check_passes_after_update_and_commit(loosened_repo: Path) -> None:
    _update_and_commit(loosened_repo, "drop IsOwner")

    result = _cli(loosened_repo, "check")

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert result.stdout == "authz.lock: up to date\n"
    assert git(loosened_repo, "status", "--porcelain") == ""


def test_t4_diff_reports_no_changes_after_commit(loosened_repo: Path) -> None:
    _update_and_commit(loosened_repo, "drop IsOwner")

    result = _diff(loosened_repo)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    assert result.stdout == "no changes\n"
    assert result.stderr == ""


def test_t5_reverse_patch_is_tightened(loosened_repo: Path) -> None:
    _update_and_commit(loosened_repo, "drop IsOwner")
    _replace(loosened_repo, LOOSENED, ORIGINAL)

    text = _diff(loosened_repo)
    markdown = _diff(loosened_repo, "--format", "markdown")

    assert text.returncode == EXIT_MISMATCH, text.stdout + text.stderr
    assert _summary(text.stdout) == (0, 1, 0, 0, 0)
    tightened = [line for line in text.stdout.splitlines() if line.startswith("tightened")]
    assert len(tightened) == 1, text.stdout
    assert ROUTE_KEY in tightened[0]
    assert "(R4: " in tightened[0]
    assert len(_rows(markdown.stdout, "tightened")) == 1, markdown.stdout
    assert not _rows(markdown.stdout, "loosened")
    # A tightening never fails a run that only gates on loosened routes.
    assert _diff(loosened_repo, "--fail-on", "loosened").returncode == EXIT_OK


def test_t7_custom_swap_is_changed_unknown_never_loosened(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path)
    _replace(
        repo,
        "from billing.permissions import IsOwner\n",
        "from billing.permissions import IsTenantAdmin\n",
    )
    _replace(repo, ORIGINAL, "    permission_classes = [IsAuthenticated, IsTenantAdmin]\n")

    markdown = _diff(repo, "--format", "markdown")
    text = _diff(repo)

    assert markdown.returncode == EXIT_MISMATCH, markdown.stdout + markdown.stderr
    assert _summary(markdown.stdout) == (0, 0, 0, 0, 1)
    assert not _rows(markdown.stdout, "loosened")
    rows = _rows(markdown.stdout, "changed-unknown")
    assert len(rows) == 1, markdown.stdout
    assert "`R3: " in rows[0]
    assert IS_TENANT_ADMIN in rows[0]
    assert not [line for line in text.stdout.splitlines() if line.startswith("loosened")]
    assert _diff(repo, "--fail-on", "loosened").returncode == EXIT_OK


# docs/scenario.md -------------------------------------------------------------------------


def _block(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(<!-- {re.escape(name)}:start -->\n)(.*?)(<!-- {re.escape(name)}:end -->)", re.DOTALL
    )


def _fenced(language: str, text: str) -> str:
    return f"```{language}\n{text}```\n"


def scenario_blocks(tmp_path: Path) -> dict[str, str]:
    """The generated blocks of docs/scenario.md, keyed by marker name."""
    repo = make_repo(FIXTURE, tmp_path)
    _loosen(repo)
    diff = _diff(repo, "--format", "markdown")
    assert diff.returncode == EXIT_MISMATCH, diff.stderr
    check = _cli(repo, "check")
    assert check.returncode == EXIT_MISMATCH, check.stderr
    return {
        "scenario": _fenced("markdown", diff.stdout),
        "scenario-check": _fenced("text", check.stdout),
    }


def test_t6_scenario_doc_matches_actual_output(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    assert DOC.is_file(), f"{DOC} is missing"
    text = DOC.read_text(encoding="utf-8")
    blocks = scenario_blocks(tmp_path)

    if request.config.getoption("--update-docs"):
        for name, content in blocks.items():
            pattern = _block(name)
            assert pattern.search(text), f"no {name} markers in {DOC.name}"
            text = pattern.sub(lambda m, c=content: m.group(1) + c + m.group(3), text)
        DOC.write_text(text, encoding="utf-8")
        pytest.skip(f"rewrote the generated blocks in {DOC.name}")

    hint = "docs/scenario.md is stale; run `pytest tests/test_scenario.py --update-docs`"
    for name, content in blocks.items():
        match = _block(name).search(text)
        assert match, f"no <!-- {name}:start --> / <!-- {name}:end --> markers in {DOC.name}"
        assert match.group(2) == content, f"{name} block: {hint}"

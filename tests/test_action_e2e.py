"""Tests for SHA-234: the action's end-to-end workflow and its helper scripts.

T1, T2, T3 and T5 are jobs of `.github/workflows/action-e2e.yml` and run on GitHub. This
file covers T4 (the report assertion script against a saved markdown sample), runs the
workflow's prepare and assert steps locally on the scenario fixture, and checks the
workflow's structure so that a broken job definition fails here before it reaches GitHub.

`tests/data/action-report-loosened.md` is the scenario report from `docs/scenario.md`,
which SHA-231's T6 keeps equal to what `authzlock diff` prints.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from authzlock.errors import EXIT_MISMATCH, EXIT_OK
from harness import project_env, run_cli

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts" / "ci"
ASSERT_SUMMARY = SCRIPTS / "assert_summary.py"
PREPARE = SCRIPTS / "prepare_scenario.py"
CHECK_COMMENT = SCRIPTS / "check_sticky_comment.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "action-e2e.yml"
SAMPLE = REPO_ROOT / "tests" / "data" / "action-report-loosened.md"
SCENARIO_DOC = REPO_ROOT / "docs" / "scenario.md"

EXPECTED_SUMMARY = "1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent"
CLEAN_SUMMARY = "0 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown, 0 equivalent"
VIEW = "billing.views.InvoiceDetailView"
LOOSENED_ARGS = (
    "--summary",
    EXPECTED_SUMMARY,
    "--row",
    "loosened",
    "--row-contains",
    "DELETE",
    "--row-contains",
    VIEW,
)
CLEAN_ARGS = ("--summary", CLEAN_SUMMARY, "--contains", "no access-control changes")
MARKER = "<!-- authzlock -->"


def _script(path: Path, *args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"authzlock_ci_{path.stem}", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# T4: the assertion script -------------------------------------------------------------------


def test_t4_summary_parser_accepts_expected_and_rejects_other(tmp_path: Path) -> None:
    ok = _script(ASSERT_SUMMARY, str(SAMPLE), *LOOSENED_ARGS)

    assert ok.returncode == 0, ok.stdout + ok.stderr
    # The log shows the matched row, so AC1's "log shows the markdown row" holds.
    assert "| loosened | DELETE,GET |" in ok.stdout
    assert f"`{VIEW}`" in ok.stdout

    two = tmp_path / "two-loosened.md"
    text = SAMPLE.read_text(encoding="utf-8")
    assert text.count(EXPECTED_SUMMARY) == 1
    two.write_text(text.replace("1 loosened,", "2 loosened,"), encoding="utf-8")

    bad = _script(ASSERT_SUMMARY, str(two), *LOOSENED_ARGS)

    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "2 loosened, 0 tightened" in bad.stderr
    assert EXPECTED_SUMMARY in bad.stderr


def test_extra_summary_parser_reads_lines_with_and_without_equivalent() -> None:
    module = _load(ASSERT_SUMMARY)
    old = "1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown"
    new = f"{old}, 2 equivalent"
    report = f"# report\n\n{old}\n\n{new}\n\n{new}, 3 surplus\n"

    # Reports from 0.1.x end at changed-unknown; later ones add equivalent (SHA-239).
    assert module.summary_lines(report) == [old, new]


def test_extra_sample_is_the_scenario_doc_report() -> None:
    """The saved sample is the report docs/scenario.md shows, which SHA-231's T6 keeps true."""
    doc = SCENARIO_DOC.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- scenario:start -->\n```markdown\n(.*?)```\n<!-- scenario:end -->", doc, re.DOTALL
    )
    assert match, "no scenario block in docs/scenario.md"
    assert SAMPLE.read_text(encoding="utf-8") == match.group(1)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--row", "tightened"), "expected one 'tightened' row, found 0"),
        (("--row", "loosened", "--row-contains", "POST"), "does not contain 'POST'"),
        (("--contains", "no access-control changes"), "does not contain"),
        (("--row-contains", "DELETE"), "--row-contains needs --row"),
    ],
)
def test_extra_assert_summary_reports_each_failed_check(
    args: tuple[str, ...], message: str
) -> None:
    result = _script(ASSERT_SUMMARY, str(SAMPLE), *args)

    assert result.returncode in {1, 2}, result.stdout + result.stderr
    assert message in result.stderr


def test_extra_assert_summary_needs_exactly_one_summary_line(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("<!-- authzlock -->\nno summary here\n", encoding="utf-8")

    result = _script(ASSERT_SUMMARY, str(report), "--summary", EXPECTED_SUMMARY)

    assert result.returncode == 1
    assert "expected one summary line, found 0" in result.stderr
    missing = _script(ASSERT_SUMMARY, str(tmp_path / "missing.md"))
    assert missing.returncode == 2
    assert "cannot read" in missing.stderr


# The workflow's prepare and assert steps, run locally ---------------------------------------


def _prepared_report(tmp_path: Path, *flags: str) -> tuple[Path, subprocess.CompletedProcess[str]]:
    repo = tmp_path / "scenario"
    prepared = _script(PREPARE, str(repo), *flags)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    result = run_cli(
        ["diff", "--base", "HEAD", "--format", "markdown", "--settings", "settings"],
        cwd=repo,
        env=project_env(repo),
    )
    report = tmp_path / "authzlock-diff.md"
    report.write_text(result.stdout, encoding="utf-8")
    return report, result


def test_extra_prepared_loosened_scenario_passes_the_t1_assertions(tmp_path: Path) -> None:
    report, result = _prepared_report(tmp_path, "--loosen")

    assert result.returncode == EXIT_MISMATCH, result.stdout + result.stderr
    checked = _script(ASSERT_SUMMARY, str(report), *LOOSENED_ARGS)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    repo = tmp_path / "scenario"
    assert (repo / "authz.lock").is_file()
    assert not list(repo.rglob("*.expected"))
    assert not (repo / "billing" / "views.py.orig").exists()


def test_extra_prepared_clean_scenario_passes_the_t2_assertions(tmp_path: Path) -> None:
    report, result = _prepared_report(tmp_path)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    checked = _script(ASSERT_SUMMARY, str(report), *CLEAN_ARGS)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    loosened = _script(ASSERT_SUMMARY, str(report), *LOOSENED_ARGS)
    assert loosened.returncode == 1


def test_extra_prepare_refuses_an_existing_directory(tmp_path: Path) -> None:
    result = _script(PREPARE, str(tmp_path))

    assert result.returncode == 2
    assert "already exists" in result.stderr


# The sticky-comment check (T3's assertion) ---------------------------------------------------


def _comment(comment_id: int, body: str, created: str = "2026-10-01T00:00:00Z") -> dict[str, Any]:
    return {"id": comment_id, "body": body, "created_at": created}


def test_extra_sticky_comment_check_accepts_one_updated_comment() -> None:
    check = _load(CHECK_COMMENT)
    body = f"{MARKER}\n{EXPECTED_SUMMARY}\n_run 42_\n"
    comments = [_comment(1, "a human comment"), _comment(7, body)]

    assert check.problems(comments, comment_id=7, expected=[EXPECTED_SUMMARY, "run 42"]) == []


def test_extra_sticky_comment_check_rejects_duplicates_and_stale_bodies() -> None:
    check = _load(CHECK_COMMENT)
    stale = f"{MARKER}\n{CLEAN_SUMMARY}\n"
    comments = [_comment(7, stale), _comment(8, f"{MARKER}\n{EXPECTED_SUMMARY}\n")]

    found = check.problems(comments, comment_id=7, expected=[EXPECTED_SUMMARY])

    assert any("expected exactly one authzlock comment, found 2" in p for p in found), found
    only_stale = check.problems([_comment(7, stale)], comment_id=7, expected=[EXPECTED_SUMMARY])
    assert only_stale == [f"the comment body does not contain {EXPECTED_SUMMARY!r}"]
    other_id = check.problems([_comment(8, stale)], comment_id=7, expected=[])
    assert other_id == ["the authzlock comment is 8, expected 7"]
    assert check.problems([], comment_id=7, expected=[]) == [
        "expected exactly one authzlock comment, found 0"
    ]


# The workflow file ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _action_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job["steps"] if step.get("uses") == "./"]


AUTOMATIC = {"loosened": "false", "clean": "false", "fails-when-loosened": "true"}


def test_extra_workflow_triggers_jobs_and_permissions(workflow: dict[str, Any]) -> None:
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML parses `on` as True
    assert "pull_request" in triggers
    pr_number = triggers["workflow_dispatch"]["inputs"]["pr_number"]
    assert pr_number["required"] is True
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {*AUTOMATIC, "fastapi-loosened", "sticky-comment"}
    for name, job in workflow["jobs"].items():
        assert "needs" not in job, f"job {name} must not depend on another job"


@pytest.mark.parametrize("name", sorted(AUTOMATIC))
def test_extra_automatic_jobs_run_the_local_action_on_a_temp_repo(
    workflow: dict[str, Any], name: str
) -> None:
    job = workflow["jobs"][name]
    assert "if" not in job, f"{name} must run on every pull request"
    (step,) = _action_steps(job)
    inputs = step["with"]
    assert inputs["comment"] == "false"
    assert inputs["fail-on-loosened"] == AUTOMATIC[name]
    assert inputs["base-ref"] == "HEAD", "a temp repo has no origin; base-ref is required"
    assert inputs["settings-module"] == "settings"
    assert "runner.temp" in inputs["working-directory"]
    assert inputs["python-version"] == "", "the action must use the Python with Django on it"

    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "scripts/ci/prepare_scenario.py" in runs
    assert ("--loosen" in runs) == (name != "clean")


@pytest.mark.parametrize("name", ["loosened", "clean"])
def test_extra_report_jobs_assert_the_report_from_the_step_output(
    workflow: dict[str, Any], name: str
) -> None:
    job = workflow["jobs"][name]
    (action,) = _action_steps(job)
    asserts = [s for s in job["steps"] if "scripts/ci/assert_summary.py" in s.get("run", "")]
    assert len(asserts) == 1
    step = asserts[0]
    assert step["env"]["REPORT"] == f"${{{{ steps.{action['id']}.outputs.report-path }}}}"
    expected = EXPECTED_SUMMARY if name == "loosened" else CLEAN_SUMMARY
    assert expected in step["run"]
    if name == "loosened":
        assert all(text in step["run"] for text in ("--row loosened", "DELETE", VIEW))
    else:
        assert "no access-control changes" in step["run"]


def test_extra_fails_when_loosened_checks_the_step_outcome(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["fails-when-loosened"]
    (action,) = _action_steps(job)
    assert action["continue-on-error"] is True
    outcome = f"steps.{action['id']}.outcome"
    checks = [s for s in job["steps"] if outcome in str(s.get("env", {}))]
    assert len(checks) == 1, f"one step must read {outcome}"
    assert "failure" in checks[0]["run"]


def test_extra_sticky_comment_job_is_manual_and_upserts_twice(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["sticky-comment"]
    assert job["if"].replace(" ", "") == "github.event_name=='workflow_dispatch'"
    assert job["permissions"] == {"contents": "read", "pull-requests": "write"}
    actions = _action_steps(job)
    assert len(actions) == 2
    for step in actions:
        assert step["with"]["comment"] == "false"
        assert step["with"]["base-ref"] == "HEAD"
    upserts = [s for s in job["steps"] if "upsert-comment" in s.get("run", "")]
    assert len(upserts) == 2
    for step in upserts:
        assert step["env"]["PR_NUMBER"] == "${{ inputs.pr_number }}"
        assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "scripts/ci/check_sticky_comment.py" in job["steps"][-1]["run"]


def test_extra_run_steps_take_expressions_through_env_only(workflow: dict[str, Any]) -> None:
    """`pr_number` and step outputs reach scripts through env, never pasted into the script."""
    for name, job in workflow["jobs"].items():
        for step in job["steps"]:
            if "run" in step:
                assert "${{" not in step["run"], f"{name}: {step.get('name')!r} must use env"


# SHA-305: the FastAPI job ------------------------------------------------------------------

FASTAPI_LOOSENED_ARGS = (
    "--summary",
    EXPECTED_SUMMARY,
    "--row",
    "loosened",
    "--row-contains",
    "GET",
    "--row-contains",
    "main.token_info",
)


def _prepared_fastapi_report(tmp_path: Path, *flags: str) -> tuple[Path, Any]:
    repo = tmp_path / "fastapi"
    prepared = _script(PREPARE, str(repo), "--fastapi", *flags)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    result = run_cli(
        ["diff", "--base", "HEAD", "--format", "markdown", "--app", "main:app"],
        cwd=repo,
        env=project_env(repo),
    )
    report = tmp_path / "authzlock-diff.md"
    report.write_text(result.stdout, encoding="utf-8")
    return report, result


def test_sha305_t2_prepared_fastapi_loosened_repo_gives_one_loosened(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    report, result = _prepared_fastapi_report(tmp_path, "--loosen")

    assert result.returncode == EXIT_MISMATCH, result.stdout + result.stderr
    checked = _script(ASSERT_SUMMARY, str(report), *FASTAPI_LOOSENED_ARGS)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "R10" in report.read_text(encoding="utf-8")


def test_sha305_t2_prepared_fastapi_clean_repo_has_no_changes(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    report, result = _prepared_fastapi_report(tmp_path)

    assert result.returncode == EXIT_OK, result.stdout + result.stderr
    checked = _script(ASSERT_SUMMARY, str(report), *CLEAN_ARGS)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_sha305_t3_fastapi_job_runs_the_local_action_with_app(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["fastapi-loosened"]
    assert "if" not in job
    (action,) = _action_steps(job)
    inputs = action["with"]
    assert inputs["app"] == "main:app"
    assert "settings-module" not in inputs
    assert inputs["base-ref"] == "HEAD"
    assert inputs["comment"] == "false"
    assert inputs["python-version"] == ""
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "prepare_scenario.py" in runs and "--fastapi --loosen" in runs
    assert "fastapi" in runs
    asserts = [s for s in job["steps"] if "scripts/ci/assert_summary.py" in s.get("run", "")]
    assert len(asserts) == 1
    assert asserts[0]["env"]["REPORT"] == f"${{{{ steps.{action['id']}.outputs.report-path }}}}"
    assert all(text in asserts[0]["run"] for text in (EXPECTED_SUMMARY, "main.token_info"))

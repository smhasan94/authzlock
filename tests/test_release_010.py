"""Tests for SHA-237: the 0.1.0 changelog, the `v1` tag check and the post-release workflow.

T1, T2, T3 and T6 are integration checks run on GitHub after the release; their run URLs are
recorded on the ticket. T4 runs scripts/ci/check_v1_tag.py in a temporary git repository.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from harness import GIT_ENV

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_V1 = REPO_ROOT / "scripts" / "ci" / "check_v1_tag.py"
VERIFY = REPO_ROOT / ".github" / "workflows" / "post-release-verify.yml"
GIT_IDENTITY = ("-c", "user.name=authzlock test", "-c", "user.email=test@authzlock.invalid")


def _changelog_section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"CHANGELOG.md has no '## {heading}' section"
    return match.group(1)


# T5 ---------------------------------------------------------------------------------------


def test_t5_changelog_010_section_complete(repo_root: Path) -> None:
    text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[0\.1\.0\] - \d{4}-\d{2}-\d{2}$", text, re.M), "no dated 0.1.0"
    assert text.index("## [Unreleased]") < text.index("## [0.1.0]")

    released = _changelog_section(text, "[0.1.0]")
    for item in (
        "`authzlock update`",
        "`authzlock check`",
        "`authzlock diff",
        "schema version 1",
        "GitHub Action",
        "pre-commit hooks",
    ):
        assert item in released, item


def test_extra_version_is_010(repo_root: Path) -> None:
    text = (repo_root / "src" / "authzlock" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.0"' in text


# T4 ---------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    env = dict(os.environ)
    for key, value in GIT_ENV.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    subprocess.run(
        ["git", *GIT_IDENTITY, *args], cwd=repo, env=env, capture_output=True, check=True
    )


@pytest.fixture
def tagged_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    _git(repo, "tag", "-a", "v0.1.0", "-m", "authzlock 0.1.0")
    return repo


def _check_v1(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_V1), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_t4_v1_tag_matches_release_tag(tagged_repo: Path) -> None:
    _git(tagged_repo, "tag", "-a", "v1", "-m", "authzlock v1", "v0.1.0")
    result = _check_v1(tagged_repo, "v0.1.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "v1 and v0.1.0 point at" in result.stdout


def test_t4_v1_tag_on_another_commit_fails(tagged_repo: Path) -> None:
    _git(tagged_repo, "commit", "-q", "--allow-empty", "-m", "second")
    _git(tagged_repo, "tag", "v1")
    result = _check_v1(tagged_repo, "v0.1.0")
    assert result.returncode == 1
    assert "v1" in result.stderr and "v0.1.0" in result.stderr


def test_t4_missing_v1_tag_fails(tagged_repo: Path) -> None:
    result = _check_v1(tagged_repo, "v0.1.0")
    assert result.returncode == 1
    assert "v1" in result.stderr


# Post-release workflow (runs T2, T3 and T4 on GitHub) --------------------------------------


@pytest.fixture(scope="module")
def verify() -> dict[str, Any]:
    assert VERIFY.is_file(), "post-release-verify.yml is missing"
    loaded = yaml.safe_load(VERIFY.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _run_lines(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_extra_verify_is_manual_with_a_version_input(verify: dict[str, Any]) -> None:
    triggers = verify[True] if True in verify else verify["on"]  # YAML parses `on` as True
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["version"]["required"] is True


def test_extra_verify_installs_from_pypi_on_310_and_313(verify: dict[str, Any]) -> None:
    job = verify["jobs"]["install"]
    assert job["strategy"]["matrix"]["python"] == ["3.10", "3.13"]
    runs = _run_lines(job)
    assert 'authzlock=="$VERSION"' in runs
    assert "authzlock --version" in runs
    # The quickstart test must import the installed package, not the checkout.
    assert "rm -rf src" in runs
    # The drf_viewsets fixture the quickstart copies imports drf-nested-routers.
    assert "drf-nested-routers" in runs
    assert "tests/test_readme.py::test_t1_quickstart_commands_run_as_documented" in runs


def test_extra_verify_checks_v1_and_uses_it(verify: dict[str, Any]) -> None:
    assert "scripts/ci/check_v1_tag.py" in _run_lines(verify["jobs"]["v1-tag"])
    uses = [step.get("uses", "") for step in verify["jobs"]["action-v1"]["steps"]]
    assert "smhasan94/authzlock@v1" in uses


def test_extra_verify_needs_no_secrets() -> None:
    assert "secrets." not in VERIFY.read_text(encoding="utf-8")

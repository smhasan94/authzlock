"""Tests for SHA-233: the `authzlock-check` and `authzlock-update` pre-commit hooks.

The integration tests (T1 to T4, T6) run the real `pre-commit` against a temp git repo that
holds the drf_viewsets fixture project at its root. `pre-commit try-repo` cannot pass
`additional_dependencies`, and the hook environment needs Django and DRF, so each target
repo instead gets the `.pre-commit-config.yaml` that docs/pre-commit.md tells users to
write, pointing at a local git repo built from this checkout (`hook_source`). The hook
environment pins the Django and DRF versions of the running test environment, so every
nox cell exercises its own versions. Building that environment installs packages from
PyPI once per session, in a session-private `PRE_COMMIT_HOME`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
import yaml

from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH
from harness import FIXTURES, run_cli

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "pre-commit.md"
FIXTURE = "drf_viewsets"
SUMMARY_PATH = "^invoices/summary/$"
SUMMARY_KEY = "GET ^invoices/summary/$ -> billing.views.InvoiceViewSet"
HINT = "run `authzlock update` and commit authz.lock"
# Files of the authzlock checkout that pre-commit needs to install the hook package.
HOOK_SOURCE_FILES = ("pyproject.toml", "README.md", "LICENSE", ".pre-commit-hooks.yaml")
GIT_IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", *GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def hook_source(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A git repo with this checkout's package and hooks file; returns (path, commit)."""
    repo = tmp_path_factory.mktemp("hook-source")
    for name in HOOK_SOURCE_FILES:
        shutil.copy(REPO_ROOT / name, repo / name)
    shutil.copytree(
        REPO_ROOT / "src",
        repo / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _git(["init", "-q"], repo)
    _git(["add", "."], repo)
    _git(["commit", "-q", "-m", "hook source"], repo)
    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, rev


@pytest.fixture(scope="session")
def precommit_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Shared across the session so the hook environment is built once."""
    return tmp_path_factory.mktemp("pre-commit-home")


def _additional_dependencies() -> list[str]:
    """The test environment's Django, DRF and nested routers, pinned exactly."""
    return [
        f"{dist}=={version(dist)}"
        for dist in ("django", "djangorestframework", "drf-nested-routers")
    ]


def _config(source: tuple[Path, str], hook: str, args: list[str] | None = None) -> str:
    entry: dict[str, Any] = {"id": hook, "additional_dependencies": _additional_dependencies()}
    if args is not None:
        entry["args"] = args
    repos = [{"repo": str(source[0]), "rev": source[1], "hooks": [entry]}]
    return yaml.safe_dump({"repos": repos}, sort_keys=False)


def _target_repo(
    tmp_path: Path,
    source: tuple[Path, str],
    hook: str,
    *,
    args: list[str] | None = None,
    lockfile: bool = True,
) -> Path:
    """A git repo with the fixture project at its root, the hook configured, all staged."""
    repo = tmp_path / "target"
    shutil.copytree(
        FIXTURES / FIXTURE,
        repo,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "authz.lock*"),
    )
    (repo / ".pre-commit-config.yaml").write_text(_config(source, hook, args), encoding="utf-8")
    if lockfile:
        result = run_cli(["update"], cwd=repo, fixture=FIXTURE)
        assert result.returncode == 0, result.stderr
    _git(["init", "-q"], repo)
    _git(["add", "."], repo)
    return repo


def _pre_commit(
    repo: Path, hook: str, home: Path, *, settings_env: bool = True
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "PRE_COMMIT")) and key != "DJANGO_SETTINGS_MODULE"
    }
    env["PRE_COMMIT_HOME"] = str(home)
    env["PRE_COMMIT_COLOR"] = "never"
    if settings_env:
        env["DJANGO_SETTINGS_MODULE"] = "settings"
    return subprocess.run(
        [str(Path(sys.executable).parent / "pre-commit"), "run", hook, "--all-files"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _remove_summary_route(lockfile: Path) -> None:
    data = yaml.safe_load(lockfile.read_text(encoding="utf-8"))
    data["routes"] = [route for route in data["routes"] if route["path"] != SUMMARY_PATH]
    lockfile.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.mark.slow
def test_t1_hook_passes_with_fresh_lockfile(
    tmp_path: Path, hook_source: tuple[Path, str], precommit_home: Path
) -> None:
    repo = _target_repo(tmp_path, hook_source, "authzlock-check")

    result = _pre_commit(repo, "authzlock-check", precommit_home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^authzlock check\.+Passed$", result.stdout, re.MULTILINE), result.stdout


@pytest.mark.slow
def test_t2_hook_fails_with_stale_lockfile_and_prints_diff(
    tmp_path: Path, hook_source: tuple[Path, str], precommit_home: Path
) -> None:
    repo = _target_repo(tmp_path, hook_source, "authzlock-check")
    _remove_summary_route(repo / "authz.lock")
    before = (repo / "authz.lock").read_bytes()

    result = _pre_commit(repo, "authzlock-check", precommit_home)

    assert result.returncode != 0, result.stdout
    assert re.search(r"^authzlock check\.+Failed$", result.stdout, re.MULTILINE), result.stdout
    assert f"- exit code: {EXIT_MISMATCH}" in result.stdout
    assert "authz.lock is out of date." in result.stdout
    assert f"added:\n  {SUMMARY_KEY}\n" in result.stdout
    assert HINT in result.stdout
    assert (repo / "authz.lock").read_bytes() == before


@pytest.mark.slow
def test_t3_settings_arg_replaces_env_var(
    tmp_path: Path, hook_source: tuple[Path, str], precommit_home: Path
) -> None:
    with_args = _target_repo(
        tmp_path / "args", hook_source, "authzlock-check", args=["--settings", "settings"]
    )
    without_args = _target_repo(tmp_path / "plain", hook_source, "authzlock-check")

    result = _pre_commit(with_args, "authzlock-check", precommit_home, settings_env=False)
    control = _pre_commit(without_args, "authzlock-check", precommit_home, settings_env=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^authzlock check\.+Passed$", result.stdout, re.MULTILINE), result.stdout
    assert control.returncode != 0, control.stdout
    assert f"- exit code: {EXIT_ERROR}" in control.stdout
    assert "No Django settings module given." in control.stdout


@pytest.mark.slow
def test_t4_update_hook_fails_once_then_passes(
    tmp_path: Path, hook_source: tuple[Path, str], precommit_home: Path
) -> None:
    repo = _target_repo(tmp_path, hook_source, "authzlock-update")
    lockfile = repo / "authz.lock"
    fresh = lockfile.read_bytes()
    _remove_summary_route(lockfile)
    _git(["add", "authz.lock"], repo)
    assert lockfile.read_bytes() != fresh

    first = _pre_commit(repo, "authzlock-update", precommit_home)
    rewritten = lockfile.read_bytes()
    second = _pre_commit(repo, "authzlock-update", precommit_home)

    assert first.returncode != 0, first.stdout
    assert re.search(r"^authzlock update\.+Failed$", first.stdout, re.MULTILINE), first.stdout
    assert "files were modified by this hook" in first.stdout
    assert rewritten == fresh
    assert second.returncode == 0, second.stdout + second.stderr
    assert re.search(r"^authzlock update\.+Passed$", second.stdout, re.MULTILINE)
    assert lockfile.read_bytes() == fresh


def _doc_yaml_blocks() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return re.findall(r"^```yaml\n(.*?)^```$", text, re.MULTILINE | re.DOTALL)


def test_t5_docs_config_example_parses_and_names_hook() -> None:
    blocks = _doc_yaml_blocks()
    configs = [yaml.safe_load(block) for block in blocks]
    complete = [c for c in configs if isinstance(c, dict) and "repos" in c]
    assert complete, "docs/pre-commit.md needs a complete .pre-commit-config.yaml example"

    config = complete[0]
    repo = config["repos"][0]
    assert repo["repo"] == "https://github.com/smhasan94/authzlock"
    assert isinstance(repo["rev"], str) and repo["rev"]
    hooks = {hook["id"]: hook for hook in repo["hooks"]}
    assert "authzlock-check" in hooks
    deps = hooks["authzlock-check"]["additional_dependencies"]
    assert any(dep.lower().startswith("django") for dep in deps)
    assert any(dep.lower().startswith("djangorestframework") for dep in deps)
    assert hooks["authzlock-check"]["args"][0] == "--settings"


def test_t5_hooks_file_declares_both_hooks() -> None:
    hooks = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    by_id = {hook["id"]: hook for hook in hooks}

    assert set(by_id) == {"authzlock-check", "authzlock-update"}
    for hook_id, command in (("authzlock-check", "check"), ("authzlock-update", "update")):
        hook = by_id[hook_id]
        assert hook["language"] == "python"
        assert hook["pass_filenames"] is False
        assert hook["always_run"] is True
        assert hook["entry"].split()[-1] == command


@pytest.mark.slow
def test_t6_missing_lockfile_exits_2_with_hint_not_traceback(
    tmp_path: Path, hook_source: tuple[Path, str], precommit_home: Path
) -> None:
    repo = _target_repo(tmp_path, hook_source, "authzlock-check", lockfile=False)

    result = _pre_commit(repo, "authzlock-check", precommit_home)

    assert result.returncode != 0, result.stdout
    assert f"- exit code: {EXIT_ERROR}" in result.stdout
    assert "authzlock: authz.lock not found." in result.stdout
    assert "Run `authzlock update` to create it" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not (repo / "authz.lock").exists()

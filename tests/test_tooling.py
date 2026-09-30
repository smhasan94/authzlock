"""Tooling tests for SHA-182: T2, T3, T4, T6 and one extra check."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def _tool(name: str) -> str:
    """Path to a console script installed next to the running interpreter."""
    return str(Path(sys.executable).parent / name)


def _mypy(target: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            _tool("mypy"),
            "--config-file",
            str(PYPROJECT),
            "--cache-dir",
            str(cache),
            str(target),
        ],
        cwd=REPO_ROOT,
    )


def test_t2_ruff_reports_unused_import_with_project_config(tmp_path: Path) -> None:
    bad = tmp_path / "unused.py"
    bad.write_text("import os\n", encoding="utf-8")

    result = _run(
        [_tool("ruff"), "check", "--config", str(PYPROJECT), "--no-cache", str(bad)],
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "F401" in result.stdout
    assert "unused.py" in result.stdout


def test_t3_mypy_strict_rejects_untyped_function(tmp_path: Path) -> None:
    mod = tmp_path / "untyped.py"
    mod.write_text("def f(x):\n    return x\n", encoding="utf-8")

    result = _mypy(mod, tmp_path / "cache")

    assert result.returncode != 0, result.stdout
    assert "missing a type annotation" in result.stdout


def test_t6_mypy_reports_unused_type_ignore(tmp_path: Path) -> None:
    mod = tmp_path / "ignored.py"
    mod.write_text("x: int = 1  # type: ignore\n", encoding="utf-8")

    result = _mypy(mod, tmp_path / "cache")

    assert result.returncode != 0, result.stdout
    assert "Unused" in result.stdout and "type: ignore" in result.stdout


@pytest.mark.slow
def test_t4_precommit_blocks_unformatted_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(REPO_ROOT / ".pre-commit-config.yaml", repo)
    shutil.copy(PYPROJECT, repo)
    bad = repo / "bad.py"
    ugly = "x  =  1\ndef  f( a,b ):\n  return a+b\n"
    bad.write_text(ugly, encoding="utf-8")

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com"}
    for cmd in (["git", "init", "-q"], ["git", "add", "."]):
        assert subprocess.run(cmd, cwd=repo, env=env, check=False).returncode == 0

    result = subprocess.run(
        [_tool("pre-commit"), "run", "--all-files"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert bad.read_text(encoding="utf-8") != ugly
    assert "x = 1" in bad.read_text(encoding="utf-8")


def test_extra_precommit_ruff_rev_matches_dev_extra() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    ruff_repos = [r for r in config["repos"] if r["repo"].endswith("/ruff-pre-commit")]
    assert len(ruff_repos) == 1
    hook_version = ruff_repos[0]["rev"].lstrip("v")

    match = re.search(r'"ruff==([0-9.]+)"', PYPROJECT.read_text(encoding="utf-8"))
    assert match, "dev extra must pin ruff exactly"
    assert hook_version == match.group(1)

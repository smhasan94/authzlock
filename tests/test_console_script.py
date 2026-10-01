"""Tests for SHA-283: the installed `authzlock` command loads the project from its root.

T1, T2 and T5 run the console script installed next to the test interpreter, not
`python -m authzlock`, with `PYTHONPATH` removed, so the project is importable only if
authzlock puts the current directory on `sys.path` itself.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from authzlock.errors import EXIT_ERROR, EXIT_OK
from harness import GIT_ENV, git, make_repo

SCRIPT = Path(sys.executable).parent / ("authzlock.exe" if os.name == "nt" else "authzlock")
FIXTURE = "drf_viewsets"
README = Path(__file__).resolve().parent.parent / "README.md"
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```$", re.DOTALL | re.MULTILINE)


def _script_env() -> dict[str, str]:
    """The reader's shell: no PYTHONPATH, the fixture's settings module, test git settings."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for key, value in GIT_ENV.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env["DJANGO_SETTINGS_MODULE"] = "settings"
    return env


def _script(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.is_file(), f"no authzlock console script next to {sys.executable}"
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=cwd,
        env=_script_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_t1_console_script_update_from_project_root(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile=None)

    result = _script("update", cwd=repo)

    assert result.returncode == EXIT_OK, result.stderr
    assert (repo / "authz.lock").is_file()
    assert "routes" in (repo / "authz.lock").read_text(encoding="utf-8")


def test_t2_console_script_check_and_diff_from_project_root(tmp_path: Path) -> None:
    repo = make_repo(FIXTURE, tmp_path, lockfile=None)
    update = _script("update", cwd=repo)
    assert update.returncode == EXIT_OK, update.stderr
    git(repo, "add", "authz.lock")
    git(repo, "commit", "--quiet", "--message", "Add authz.lock")

    check = _script("check", cwd=repo)
    diff = _script("diff", "--base", "HEAD", cwd=repo)

    assert check.returncode == EXIT_OK, check.stderr
    assert diff.returncode == EXIT_OK, diff.stderr
    assert "no changes" in diff.stdout


def test_t3_cwd_is_added_to_sys_path_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p not in {"", os.curdir}])
    cwd = os.getcwd()
    from authzlock.django_loader import add_cwd_to_path

    add_cwd_to_path()
    add_cwd_to_path()

    assert sys.path[0] == cwd
    assert sys.path.count(cwd) == 1


def test_t3_cwd_already_on_sys_path_as_empty_string_is_not_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", ["", *sys.path])
    before = list(sys.path)
    from authzlock.django_loader import add_cwd_to_path

    add_cwd_to_path()

    assert sys.path == before


def test_t4_readme_quickstart_uses_the_authzlock_command() -> None:
    text = README.read_text(encoding="utf-8")
    blocks = [body for info, body in FENCE.findall(text) if info.strip() == "sh quickstart"]

    assert blocks, "README has no `sh quickstart` blocks"
    joined = "\n".join(blocks)
    assert re.search(r"^authzlock update\b", joined, re.MULTILINE), joined
    assert "python -m authzlock" not in joined
    assert "python -m authzlock" not in text


def test_t5_console_script_outside_project_reports_cannot_import(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _script("update", cwd=elsewhere)

    assert result.returncode == EXIT_ERROR, result.stderr
    assert "cannot import" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (elsewhere / "authz.lock").exists()

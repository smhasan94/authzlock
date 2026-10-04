"""Run authzlock extraction or the CLI against a fixture project in a separate process.

Django can only be set up once per process, so every call starts a fresh interpreter with
`PYTHONPATH` pointing at `tests/fixtures/<fixture>` and `DJANGO_SETTINGS_MODULE=settings`.
A fixture with `main.py` and no `settings.py` is a FastAPI project and gets
`AUTHZLOCK_APP=main:app` instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Blocks the named modules, then runs `python -m authzlock._dump`.
_BOOTSTRAP = """
import runpy, sys
for name in sys.argv[1:]:
    sys.modules[name] = None
sys.argv = sys.argv[:1]
runpy.run_module("authzlock._dump", run_name="__main__", alter_sys=True)
"""


def project_vars(project: Path) -> dict[str, str | None]:
    """The variables that name the project in `project`: `AUTHZLOCK_APP` for a FastAPI
    project (`main.py` without `settings.py`), `DJANGO_SETTINGS_MODULE` otherwise. The other
    one is None, meaning unset."""
    if not (project / "settings.py").exists() and (project / "main.py").exists():
        return {"AUTHZLOCK_APP": "main:app", "DJANGO_SETTINGS_MODULE": None}
    return {"DJANGO_SETTINGS_MODULE": "settings", "AUTHZLOCK_APP": None}


def fixture_env(fixture: str) -> dict[str, str]:
    """Environment that makes `fixture` the project for a child process."""
    path = FIXTURES / fixture
    if not path.is_dir():
        raise ValueError(f"no fixture project named {fixture!r} in {FIXTURES}")
    env = {**os.environ, "PYTHONPATH": str(path)}
    for key, value in project_vars(path).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_dump(
    fixture: str, *, block_modules: Iterable[str] = ()
) -> subprocess.CompletedProcess[str]:
    """Run `python -m authzlock._dump` for `fixture` and return the finished process."""
    return subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP, *block_modules],
        env=fixture_env(fixture),
        capture_output=True,
        text=True,
        check=False,
    )


def run_extract(fixture: str, *, block_modules: Iterable[str] = ()) -> dict[str, Any]:
    """Extract the inventory of `fixture` in a subprocess and return it as a dict."""
    result = run_dump(fixture, block_modules=block_modules)
    if result.returncode != 0:
        raise AssertionError(
            f"extraction of {fixture!r} exited {result.returncode}\n{result.stderr}"
        )
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def run_cli(
    args: Iterable[str],
    *,
    cwd: Path,
    fixture: str | None = None,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `python -m authzlock <args>` in `cwd` and return the finished process.

    With `fixture`, the child process gets `fixture_env(fixture)`. `env` entries are applied
    on top; a value of None removes the variable.
    """
    full_env = fixture_env(fixture) if fixture is not None else dict(os.environ)
    for key, value in (env or {}).items():
        if value is None:
            full_env.pop(key, None)
        else:
            full_env[key] = value
    return subprocess.run(
        [sys.executable, "-m", "authzlock", *args],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


# Git settings for temporary test repositories: no user or system config (so no signing or
# hooks), a fixed identity, and none of the variables a calling git hook may have set.
GIT_ENV: dict[str, str | None] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "authzlock tests",
    "GIT_AUTHOR_EMAIL": "tests@authzlock.invalid",
    "GIT_COMMITTER_NAME": "authzlock tests",
    "GIT_COMMITTER_EMAIL": "tests@authzlock.invalid",
    "GIT_DIR": None,
    "GIT_WORK_TREE": None,
    "GIT_INDEX_FILE": None,
}


def git(repo: Path, *args: str) -> str:
    """Run `git <args>` in `repo` with `GIT_ENV` and return stdout; fail on a non-zero exit."""
    env = dict(os.environ)
    for key, value in GIT_ENV.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} exited {result.returncode}\n{result.stderr}")
    return result.stdout


def init_repo(repo: Path) -> Path:
    """Create a git repository at `repo` with one empty commit and return its path."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "--quiet")
    git(repo, "commit", "--quiet", "--allow-empty", "--message", "empty")
    return repo


def project_env(repo: Path) -> dict[str, str | None]:
    """`run_cli` environment that makes the project copied into `repo` the project."""
    return {**GIT_ENV, "PYTHONPATH": str(repo), **project_vars(repo)}


def make_repo(fixture: str, tmp_path: Path, *, lockfile: str | None = "authz.lock") -> Path:
    """Copy `fixture` into a new git repository under `tmp_path` and commit it.

    With `lockfile`, `authzlock update --lockfile <lockfile>` runs first, so the commit holds
    a lockfile that matches the code; with None the commit has no lockfile. Golden files and
    bytecode are not copied. Returns the repository root, which is also the project root.
    """
    source = FIXTURES / fixture
    if not source.is_dir():
        raise ValueError(f"no fixture project named {fixture!r} in {FIXTURES}")
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=shutil.ignore_patterns("*.expected", "__pycache__"))
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    git(repo, "init", "--quiet")
    if lockfile is not None:
        result = run_cli(["update", "--lockfile", lockfile], cwd=repo, env=project_env(repo))
        if result.returncode != 0:
            raise AssertionError(f"authzlock update exited {result.returncode}\n{result.stderr}")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", f"{fixture} fixture")
    return repo


def run_generated_tests(
    project: Path, module: Path, *, select: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run pytest on the generated `module` against the Django project in `project`.

    The project directory is the rootdir and no ini file is read, so this repository's own
    `conftest.py` and pytest settings are not used; the project is on `PYTHONPATH` with
    `DJANGO_SETTINGS_MODULE=settings`, as for `make_repo` projects.
    """
    env = dict(os.environ)
    for key, value in project_env(project).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", os.devnull]
    args += ["--rootdir", str(project), str(module)]
    if select is not None:
        args += ["-k", select]
    return subprocess.run(args, cwd=project, env=env, capture_output=True, text=True, check=False)

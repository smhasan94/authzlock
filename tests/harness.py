"""Run authzlock extraction or the CLI against a fixture project in a separate process.

Django can only be set up once per process, so every call starts a fresh interpreter with
`PYTHONPATH` pointing at `tests/fixtures/<fixture>` and `DJANGO_SETTINGS_MODULE=settings`.
"""

from __future__ import annotations

import json
import os
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


def fixture_env(fixture: str) -> dict[str, str]:
    """Environment that makes `fixture` the Django project for a child process."""
    path = FIXTURES / fixture
    if not path.is_dir():
        raise ValueError(f"no fixture project named {fixture!r} in {FIXTURES}")
    return {**os.environ, "PYTHONPATH": str(path), "DJANGO_SETTINGS_MODULE": "settings"}


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

"""Shared fixtures for the authzlock test suite."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def run_python() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run the current interpreter with arguments and an optional extra environment."""

    def _run(
        args: list[str], env: Mapping[str, str] | None = None, cwd: Path = REPO_ROOT
    ) -> subprocess.CompletedProcess[str]:
        import os

        full_env = {**os.environ, **(env or {})}
        return subprocess.run(
            [sys.executable, *args],
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


@pytest.fixture(scope="session")
def nox_session_names(repo_root: Path) -> list[str]:
    """Session names as `nox -l` reports them, using the noxfile in the repo."""
    nox = Path(sys.executable).parent / "nox"
    result = subprocess.run(
        [str(nox), "-l", "--json"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return [entry["session"] for entry in json.loads(result.stdout)]

"""CI workflow tests for SHA-184 (T4, T5, two extra guards) and SHA-272 (one extra)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml


@pytest.fixture(scope="module")
def noxfile(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("authzlock_noxfile_ci", repo_root / "noxfile.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> dict[str, Any]:
    path = repo_root / ".github" / "workflows" / "ci.yml"
    assert path.is_file(), "ci.yml is missing"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _matrix_cells(job: dict[str, Any]) -> set[tuple[str, str]]:
    matrix = job["strategy"]["matrix"]
    cells = {(str(py), str(dj)) for py in matrix["python"] for dj in matrix["django"]}
    for excluded in matrix.get("exclude", []):
        cells.discard((str(excluded["python"]), str(excluded["django"])))
    for included in matrix.get("include", []):
        cells.add((str(included["python"]), str(included["django"])))
    return cells


def test_t4_nox_default_sessions_run_everything_ci_runs(
    noxfile: ModuleType, workflow: dict[str, Any]
) -> None:
    assert noxfile.nox.options.sessions == ["lint", "typecheck", "tests", "tests_min_drf"]
    assert set(noxfile.nox.options.sessions) == set(workflow["jobs"])


def test_t5_ci_matrix_cells_equal_noxfile_supported(
    noxfile: ModuleType, workflow: dict[str, Any]
) -> None:
    assert _matrix_cells(workflow["jobs"]["tests"]) == set(noxfile.SUPPORTED)


def test_extra_jobs_are_independent(workflow: dict[str, Any]) -> None:
    for name, job in workflow["jobs"].items():
        assert "needs" not in job, f"job {name} must not depend on another job"


def test_extra_triggers_cover_pull_request_and_main_push(workflow: dict[str, Any]) -> None:
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML parses `on` as True
    assert "pull_request" in triggers
    assert "main" in triggers["push"]["branches"]


def test_extra_ci_has_min_drf_job(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["tests_min_drf"]
    steps = job["steps"]
    pythons = [
        step["with"]["python-version"] for step in steps if "setup-python" in step.get("uses", "")
    ]
    assert pythons == ["3.12"]
    assert any(step.get("run") == "nox -s tests_min_drf" for step in steps)

"""Tests for SHA-284: Django is a runtime dependency and the release smoke-tests the wheel."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

SMOKE_STEP = "Smoke-test the wheel in a fresh environment"


@pytest.fixture(scope="module")
def dependencies(repo_root: Path) -> list[str]:
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", project, re.MULTILINE | re.DOTALL)
    assert match, "no [project] dependencies list"
    return re.findall(r'"([^"]+)"', match.group(1))


@pytest.fixture(scope="module")
def build_steps(repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = workflow["jobs"]["build"]["steps"]
    return steps


def test_t1_django_is_a_runtime_dependency(dependencies: list[str]) -> None:
    names = {re.split(r"[<>=!~;\[ ]", dep, maxsplit=1)[0].lower(): dep for dep in dependencies}
    assert "django" in names
    assert re.sub(r"\s", "", names["django"]).lower() == "django>=4.2"
    assert "djangorestframework" not in names


def test_t2_release_build_smoke_tests_the_wheel(build_steps: list[dict[str, Any]]) -> None:
    names = [step.get("name", "") for step in build_steps]
    assert SMOKE_STEP in names
    smoke = build_steps[names.index(SMOKE_STEP)]
    assert names.index("Build the sdist and wheel") < names.index(SMOKE_STEP)
    assert names.index(SMOKE_STEP) < names.index("Upload the distributions")
    script = smoke["run"]
    assert "venv" in script
    assert "dist/*.whl" in script
    assert "authzlock --version" in script

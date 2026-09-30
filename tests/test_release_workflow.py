"""Release workflow tests for SHA-185: T3, T4, T5 and two extra static guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

PUBLISH_ACTION = "pypa/gh-action-pypi-publish"
RELEASE_STEPS = (
    "Update the changelog",
    "Bump the version",
    "Tag the release",
    "Push the tag",
    "Verify the install",
)


@pytest.fixture(scope="module")
def release_path(repo_root: Path) -> Path:
    path = repo_root / ".github" / "workflows" / "release.yml"
    assert path.is_file(), "release.yml is missing"
    return path


@pytest.fixture(scope="module")
def release(release_path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(release_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML parses `on` as True
    assert isinstance(triggers, dict)
    return triggers


def _publish_jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: job
        for name, job in workflow["jobs"].items()
        if any(PUBLISH_ACTION in step.get("uses", "") for step in job.get("steps", []))
    }


def test_t3_publish_uses_trusted_publishing(release: dict[str, Any]) -> None:
    jobs = _publish_jobs(release)
    assert set(jobs) == {"publish-pypi", "publish-testpypi"}
    for name, job in jobs.items():
        assert job.get("permissions", {}).get("id-token") == "write", name
        assert job["needs"] == "build", name
        for step in job["steps"]:
            if PUBLISH_ACTION in step.get("uses", ""):
                inputs = step.get("with", {})
                assert "password" not in inputs, name
                assert "user" not in inputs, name


def test_t3_testpypi_job_targets_testpypi_only(release: dict[str, Any]) -> None:
    jobs = _publish_jobs(release)
    test_step = next(
        s for s in jobs["publish-testpypi"]["steps"] if "uses" in s and PUBLISH_ACTION in s["uses"]
    )
    assert test_step["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    prod_step = next(
        s for s in jobs["publish-pypi"]["steps"] if "uses" in s and PUBLISH_ACTION in s["uses"]
    )
    assert "repository-url" not in prod_step.get("with", {})
    assert jobs["publish-testpypi"]["environment"]["name"] == "testpypi"
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"
    assert "testpypi" in jobs["publish-testpypi"]["if"]
    assert "github.event_name == 'push'" in jobs["publish-pypi"]["if"]


def test_t4_changelog_and_releasing_docs(repo_root: Path) -> None:
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    releasing = (repo_root / "docs" / "releasing.md").read_text(encoding="utf-8")
    for step in RELEASE_STEPS:
        assert step in releasing, step


def test_t5_release_triggers_only_on_version_tags(release: dict[str, Any]) -> None:
    triggers = _triggers(release)
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*"]}
    target = triggers["workflow_dispatch"]["inputs"]["target"]
    assert target["default"] == "testpypi"
    assert target["options"] == ["testpypi", "pypi"]


def test_extra_no_secrets_referenced(release_path: Path) -> None:
    assert "secrets." not in release_path.read_text(encoding="utf-8")


def test_extra_build_checks_version_before_upload(release: dict[str, Any]) -> None:
    names = [step.get("name", "") for step in release["jobs"]["build"]["steps"]]
    check = names.index("Check the tag matches the package version")
    upload = names.index("Upload the distributions")
    assert check < upload

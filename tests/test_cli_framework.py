"""Tests for SHA-243 T1: choosing between Django and FastAPI.

The resolution table is checked against `_project` directly; a few cases run the CLI end to
end to show the choice reaches extraction and that config errors name `[tool.authzlock]`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from authzlock.cli import FailOn, Framework, _Options, _project
from authzlock.config import Config
from authzlock.errors import ProjectLoadError
from harness import FIXTURES, run_cli

PYPROJECT = Path("/repo/pyproject.toml")
NEITHER = "No Django settings module or FastAPI app given."


def _resolve(
    monkeypatch: pytest.MonkeyPatch,
    framework: Framework = Framework.auto,
    *,
    flags: tuple[str | None, str | None] = (None, None),
    env: tuple[str | None, str | None] = (None, None),
    config: tuple[str | None, str | None] = (None, None),
) -> tuple[str, str | None, Path | None]:
    """(framework, app or settings, config path) chosen for app/settings pairs per tier."""
    for name, value in zip(("AUTHZLOCK_APP", "DJANGO_SETTINGS_MODULE"), env, strict=True):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    options = _Options(
        lockfile=Path("authz.lock"),
        fail_on=FailOn.any,
        framework=framework,
        app=flags[0],
        settings=flags[1],
        config=Config(app=config[0], settings=config[1], path=PYPROJECT),
    )
    project = _project(options)
    target = project.app if project.framework is Framework.fastapi else project.settings
    return project.framework.value, target, project.config_path


@pytest.mark.parametrize(
    ("framework", "tiers", "expected"),
    [
        # One tier names one project.
        (Framework.auto, {"flags": ("main:app", None)}, ("fastapi", "main:app", None)),
        (Framework.auto, {"flags": (None, "site.settings")}, ("django", "site.settings", None)),
        (Framework.auto, {"env": ("main:app", None)}, ("fastapi", "main:app", None)),
        (Framework.auto, {"env": (None, "site.settings")}, ("django", "site.settings", None)),
        (Framework.auto, {"config": ("main:app", None)}, ("fastapi", "main:app", PYPROJECT)),
        (
            Framework.auto,
            {"config": (None, "site.settings")},
            ("django", "site.settings", PYPROJECT),
        ),
        # A higher tier wins over a lower one, whichever framework each names.
        (
            Framework.auto,
            {"flags": ("main:app", None), "env": (None, "site.settings")},
            ("fastapi", "main:app", None),
        ),
        (
            Framework.auto,
            {"flags": (None, "site.settings"), "env": ("main:app", None)},
            ("django", "site.settings", None),
        ),
        (
            Framework.auto,
            {"env": ("main:app", None), "config": (None, "site.settings")},
            ("fastapi", "main:app", None),
        ),
        # An explicit framework ignores the other kind of project, even in a higher tier.
        (
            Framework.django,
            {"flags": ("main:app", None), "config": (None, "site.settings")},
            ("django", "site.settings", PYPROJECT),
        ),
        (
            Framework.fastapi,
            {"flags": ("main:app", "site.settings")},
            ("fastapi", "main:app", None),
        ),
        (
            Framework.fastapi,
            {"env": (None, "site.settings"), "config": ("main:app", None)},
            ("fastapi", "main:app", PYPROJECT),
        ),
        # --framework django with nothing named defers to load_project's message.
        (Framework.django, {}, ("django", None, None)),
    ],
)
def test_t1_framework_auto_resolution(
    monkeypatch: pytest.MonkeyPatch,
    framework: Framework,
    tiers: dict[str, Any],
    expected: tuple[str, str | None, Path | None],
) -> None:
    assert _resolve(monkeypatch, framework, **tiers) == expected


@pytest.mark.parametrize(
    ("framework", "tiers", "message"),
    [
        (
            Framework.auto,
            {"flags": ("main:app", "site.settings")},
            "Both an app (main:app) and a settings module (site.settings) are set on the "
            "command line.\nPass --framework fastapi or --framework django to choose one.",
        ),
        (
            Framework.auto,
            {"env": ("main:app", "site.settings")},
            "Both an app (main:app) and a settings module (site.settings) are set in the "
            "environment.",
        ),
        (
            Framework.auto,
            {"config": ("main:app", "site.settings")},
            f"are set in [tool.authzlock] in {PYPROJECT}.",
        ),
        (Framework.auto, {}, NEITHER),
        (
            Framework.fastapi,
            {"env": (None, "site.settings")},
            "No FastAPI app given.\nSet AUTHZLOCK_APP or pass --app",
        ),
    ],
)
def test_t1_ambiguous_or_missing_project_is_an_error(
    monkeypatch: pytest.MonkeyPatch, framework: Framework, tiers: dict[str, Any], message: str
) -> None:
    with pytest.raises(ProjectLoadError) as raised:
        _resolve(monkeypatch, framework, **tiers)

    assert message in str(raised.value)
    assert len(str(raised.value).split("\n")) == 2


def _project_copy(tmp_path: Path, fixture: str) -> Path:
    project = tmp_path / fixture
    shutil.copytree(FIXTURES / fixture, project, ignore=shutil.ignore_patterns("*.expected"))
    return project


def test_t1_app_flag_wins_over_exported_settings_module(tmp_path: Path) -> None:
    project = _project_copy(tmp_path, "fastapi_basic")

    result = run_cli(
        ["update", "--app", "main:app"],
        cwd=project,
        env={"PYTHONPATH": str(project), "DJANGO_SETTINGS_MODULE": "settings"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "authz.lock: 10 routes written\n"


def test_t1_app_from_config_and_its_load_error_names_the_file(tmp_path: Path) -> None:
    project = _project_copy(tmp_path, "fastapi_basic")
    pyproject = project / "pyproject.toml"
    env = {"PYTHONPATH": str(project), "DJANGO_SETTINGS_MODULE": None, "AUTHZLOCK_APP": None}

    pyproject.write_text('[tool.authzlock]\napp = "main:app"\n', encoding="utf-8")
    written = run_cli(["update"], cwd=project, env=env)
    pyproject.write_text('[tool.authzlock]\napp = "main:nothing"\n', encoding="utf-8")
    failed = run_cli(["check"], cwd=project, env=env)

    assert written.returncode == 0, written.stderr
    assert failed.returncode == 2
    assert failed.stderr == (
        "authzlock: App module 'main' has no attribute 'nothing'.\n"
        "Pass --app MODULE:ATTR naming the application object.\n"
        f"The app is set in [tool.authzlock] in {pyproject}.\n"
    )


def test_t1_both_on_the_command_line_exits_2(tmp_path: Path) -> None:
    result = run_cli(
        ["update", "--app", "main:app", "--settings", "settings"],
        cwd=tmp_path,
        env={"DJANGO_SETTINGS_MODULE": None, "AUTHZLOCK_APP": None},
    )

    assert result.returncode == 2
    assert result.stderr.startswith("authzlock: Both an app (main:app) and a settings module")
    assert not (tmp_path / "authz.lock").exists()


def test_t1_framework_flag_overrides_the_guess(tmp_path: Path) -> None:
    project = _project_copy(tmp_path, "fastapi_basic")
    env = {"PYTHONPATH": str(project), "AUTHZLOCK_APP": "main:app", "DJANGO_SETTINGS_MODULE": "x"}

    result = run_cli(["update", "--framework", "fastapi"], cwd=project, env=env)

    assert result.returncode == 0, result.stderr

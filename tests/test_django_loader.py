"""Tests for SHA-197: Django bootstrap and fixture harness."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from authzlock.django_loader import load_project
from authzlock.errors import ProjectLoadError
from harness import FIXTURES, fixture_env, run_dump, run_extract

LOAD_AND_REPORT = (
    "import sys; from django.apps import apps; from authzlock.django_loader import load_project;"
    " load_project(sys.argv[1] if len(sys.argv) > 1 else None); print(apps.ready)"
)


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], env=env, capture_output=True, text=True, check=False
    )


def test_t1_load_project_reads_env_var() -> None:
    result = _run(["-c", LOAD_AND_REPORT], fixture_env("function_views"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_t2_explicit_settings_argument_wins() -> None:
    env = {**fixture_env("function_views"), "DJANGO_SETTINGS_MODULE": "bogus.settings"}
    result = _run(["-c", LOAD_AND_REPORT, "settings"], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_t3_missing_module_raises_project_load_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    with pytest.raises(ProjectLoadError) as excinfo:
        load_project("does.not.exist")
    message = str(excinfo.value)
    assert "does.not.exist" in message
    assert "cannot import" in message


def test_t4_no_settings_anywhere_gives_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    with pytest.raises(ProjectLoadError) as excinfo:
        load_project(None)
    message = str(excinfo.value)
    assert "DJANGO_SETTINGS_MODULE" in message
    assert "--settings" in message


def test_t5_two_fixtures_extract_in_one_session() -> None:
    first = run_extract("function_views")
    second = run_extract("function_views")
    other = run_extract("minimal")
    for data in (first, second, other):
        assert "schema_version" in data


def test_t6_fixture_passes_django_check() -> None:
    code = (
        "import django; django.setup();"
        " from django.core.management import call_command; call_command('check')"
    )
    result = _run(["-c", code], fixture_env("function_views"))
    assert result.returncode == 0, result.stderr
    assert "no issues" in result.stdout


def test_t7_settings_import_error_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(FIXTURES / "broken"))
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    sys.modules.pop("settings", None)
    try:
        with pytest.raises(ProjectLoadError) as excinfo:
            load_project("settings")
    finally:
        sys.modules.pop("settings", None)
    assert "boom" in str(excinfo.value)


def test_t7_dump_reports_settings_error_and_exits_2() -> None:
    result = run_dump("broken")
    assert result.returncode == 2
    assert "boom" in result.stderr
    assert "Traceback" not in result.stderr


def test_extra_dump_outputs_schema_version() -> None:
    assert run_extract("minimal")["schema_version"] == 1


def test_extra_block_modules_hides_a_module() -> None:
    data = run_extract("minimal", block_modules=("rest_framework",))
    assert data["schema_version"] == 1


def test_extra_unknown_fixture_is_rejected() -> None:
    with pytest.raises(ValueError, match="no fixture project"):
        fixture_env("nope")


def test_extra_fixture_projects_have_required_files() -> None:
    for name in ("function_views", "minimal"):
        for required in ("settings.py", "urls.py"):
            assert (Path(FIXTURES) / name / required).is_file()

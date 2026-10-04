"""Tests for SHA-238: `[tool.authzlock]` applied by `update`, `check` and `diff`.

These load a Django project, so each run is a subprocess (`run_cli`) in a project copied
under `tmp_path` next to a generated `pyproject.toml`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from harness import FIXTURES, make_repo, project_env, run_cli

WRITTEN = re.compile(r"^(?P<lockfile>\S+): (?P<count>\d+) routes? written$", re.MULTILINE)
COPY_IGNORE = shutil.ignore_patterns("*.expected", "__pycache__")


def _pyproject(directory: Path, table: str) -> Path:
    path = directory / "pyproject.toml"
    path.write_text(f'[project]\nname = "demo"\n\n[tool.authzlock]\n{table}', encoding="utf-8")
    return path


def _minimal_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(FIXTURES / "minimal", project, ignore=COPY_IGNORE)
    return project


def _written(stdout: str) -> tuple[str, int]:
    match = WRITTEN.search(stdout)
    assert match, stdout
    return match["lockfile"], int(match["count"])


def _three_settings_project(tmp_path: Path) -> Path:
    """`minimal` plus two more settings modules that give different route counts.

    `settings` is the minimal project (1 route), `fv_settings` the function_views project and
    `flag_settings` two routes on the minimal app.
    """
    project = _minimal_project(tmp_path)
    source = FIXTURES / "function_views"
    shutil.copytree(source / "shop", project / "shop", ignore=COPY_IGNORE)
    shutil.copy(source / "urls.py", project / "fv_urls.py")
    settings = (source / "settings.py").read_text(encoding="utf-8")
    (project / "fv_settings.py").write_text(
        settings.replace('ROOT_URLCONF = "urls"', 'ROOT_URLCONF = "fv_urls"'), encoding="utf-8"
    )
    minimal = (project / "settings.py").read_text(encoding="utf-8")
    (project / "flag_settings.py").write_text(
        minimal.replace('ROOT_URLCONF = "urls"', 'ROOT_URLCONF = "flag_urls"'), encoding="utf-8"
    )
    (project / "flag_urls.py").write_text(
        "from django.urls import path\n"
        "from home import views\n\n"
        'urlpatterns = [path("", views.index), path("again/", views.index)]\n',
        encoding="utf-8",
    )
    return project


def test_t1_settings_from_config_when_env_and_flag_absent(tmp_path: Path) -> None:
    project = _minimal_project(tmp_path)
    _pyproject(project, 'settings = "settings"\n')

    result = run_cli(
        ["update"], cwd=project, env={"DJANGO_SETTINGS_MODULE": None, "PYTHONPATH": None}
    )

    assert result.returncode == 0, result.stderr
    assert _written(result.stdout) == ("authz.lock", 1)
    assert (project / "authz.lock").is_file()


def test_t2_env_beats_config_and_flag_beats_env(tmp_path: Path) -> None:
    project = _three_settings_project(tmp_path)
    _pyproject(project, 'settings = "settings"\n')

    def count(*args: str, settings_env: str | None = None) -> int:
        result = run_cli(
            ["update", *args, "--lockfile", "out.lock"],
            cwd=project,
            env={"DJANGO_SETTINGS_MODULE": settings_env, "PYTHONPATH": str(project)},
        )
        assert result.returncode == 0, result.stderr
        (project / "out.lock").unlink()
        return _written(result.stdout)[1]

    from_config = count()
    from_env = count(settings_env="fv_settings")
    from_flag = count("--settings", "flag_settings", settings_env="fv_settings")

    assert from_config == 1
    assert from_flag == 2
    assert from_env not in (from_config, from_flag)


def test_t3_config_lockfile_is_relative_to_pyproject_from_subdirectory(tmp_path: Path) -> None:
    project = _minimal_project(tmp_path)
    _pyproject(project, 'lockfile = "config/authz.lock"\n')
    subdirectory = project / "home"

    update = run_cli(["update"], cwd=subdirectory, env=project_env(project))

    assert update.returncode == 0, update.stderr
    assert (project / "config" / "authz.lock").is_file()
    assert not (subdirectory / "config").exists()
    assert _written(update.stdout)[0] == str(Path("..", "config", "authz.lock"))

    check = run_cli(["check"], cwd=project, env=project_env(project))

    assert check.returncode == 0, check.stdout + check.stderr
    assert check.stdout == f"{Path('config', 'authz.lock')}: up to date\n"


def test_t4_fail_on_loosened_from_config_and_flag_override(tmp_path: Path) -> None:
    repo = make_repo("drf_apiview", tmp_path)
    _pyproject(repo, 'fail_on = "loosened"\n')
    views = repo / "api" / "views.py"
    text = views.read_text(encoding="utf-8")
    old = "class ExplicitView(APIView):\n    permission_classes = [IsAuthenticated]\n"
    assert text.count(old) == 1
    new = "class ExplicitView(APIView):\n    permission_classes = [IsAdminUser]\n"
    views.write_text(text.replace(old, new), encoding="utf-8")

    from_config = run_cli(["diff", "--base", "HEAD"], cwd=repo, env=project_env(repo))
    from_flag = run_cli(
        ["diff", "--base", "HEAD", "--fail-on", "any"], cwd=repo, env=project_env(repo)
    )

    assert "0 loosened, 1 tightened" in from_config.stdout, from_config.stdout + from_config.stderr
    assert from_config.returncode == 0
    assert from_flag.returncode == 1, from_flag.stdout + from_flag.stderr


def test_t5_table_without_keys_changes_nothing(tmp_path: Path) -> None:
    project = _minimal_project(tmp_path)
    _pyproject(project, "")

    result = run_cli(["update"], cwd=project, env=project_env(project))

    assert result.returncode == 0, result.stderr
    assert _written(result.stdout) == ("authz.lock", 1)


def test_t9_settings_import_error_names_config_file(tmp_path: Path) -> None:
    project = _minimal_project(tmp_path)
    shutil.copy(FIXTURES / "broken" / "settings.py", project / "broken_settings.py")
    path = _pyproject(project, 'settings = "broken_settings"\n')

    result = run_cli(
        ["update"], cwd=project, env={"DJANGO_SETTINGS_MODULE": None, "PYTHONPATH": None}
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "broken_settings" in result.stderr
    assert f"[tool.authzlock] in {path}" in result.stderr.replace("\n", " ")
    assert "Traceback" not in result.stderr


def test_extra_env_settings_error_does_not_name_config(tmp_path: Path) -> None:
    project = _minimal_project(tmp_path)
    _pyproject(project, 'settings = "settings"\n')

    result = run_cli(
        ["update"], cwd=project, env={"DJANGO_SETTINGS_MODULE": "nope", "PYTHONPATH": None}
    )

    assert result.returncode == 2
    assert "'nope'" in result.stderr
    assert "[tool.authzlock]" not in result.stderr

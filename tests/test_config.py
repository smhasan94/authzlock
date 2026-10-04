"""Tests for SHA-238: reading `[tool.authzlock]` from `pyproject.toml`.

Unit tests call `load_config` directly. The error cases also run the CLI in-process: a bad
table is reported before the project is loaded, so Django is never imported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from authzlock.cli import app
from authzlock.config import Config, find_pyproject, load_config
from authzlock.errors import EXIT_ERROR, ConfigError


def _pyproject(directory: Path, text: str) -> Path:
    path = directory / "pyproject.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project directory that is the current directory, with no settings env var."""
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def _assert_config_error(result: Any, path: Path, *needles: str) -> None:
    assert result.exit_code == EXIT_ERROR, result.output
    assert result.stdout == ""
    assert result.stderr.startswith("authzlock: ")
    assert "Traceback" not in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert str(path) in result.stderr
    for needle in needles:
        assert needle in result.stderr, result.stderr


def test_t5_no_pyproject_or_no_table_gives_defaults(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    found = find_pyproject(nested)
    assert found is None or tmp_path not in found.parents

    path = _pyproject(tmp_path, '[project]\nname = "demo"\n\n[tool.ruff]\nline-length = 99\n')

    assert find_pyproject(nested) == path
    config = load_config(nested)
    assert config == Config(path=path)
    assert (config.settings, config.lockfile, config.fail_on) == (None, None, None)


def test_extra_values_and_lockfile_relative_to_pyproject(tmp_path: Path) -> None:
    path = _pyproject(
        tmp_path,
        "[tool.authzlock]\n"
        'settings = "mysite.settings"\n'
        'lockfile = "config/authz.lock"\n'
        'fail_on = "loosened"\n',
    )
    nested = tmp_path / "src" / "app"
    nested.mkdir(parents=True)

    config = load_config(nested)

    assert config == Config(
        settings="mysite.settings",
        lockfile=path.parent / "config" / "authz.lock",
        fail_on="loosened",
        path=path,
    )


def test_extra_nearest_pyproject_wins(tmp_path: Path) -> None:
    _pyproject(tmp_path, '[tool.authzlock]\nsettings = "outer.settings"\n')
    inner = tmp_path / "inner"
    inner.mkdir()
    _pyproject(inner, '[tool.authzlock]\nsettings = "inner.settings"\n')

    assert load_config(inner).settings == "inner.settings"


def test_t6_unknown_key_exits_2_naming_key_and_file(project: Path) -> None:
    path = _pyproject(project, '[tool.authzlock]\nlock_file = "authz.lock"\n')

    with pytest.raises(ConfigError, match="lock_file"):
        load_config(project)
    _assert_config_error(_invoke("check"), path, "'lock_file'", "[tool.authzlock]")


def test_t7_invalid_toml_exits_2_with_line_and_no_traceback(project: Path) -> None:
    path = _pyproject(project, '[project]\nname = "demo"\n\n[tool.authzlock\nsettings = "x"\n')

    _assert_config_error(_invoke("update"), path, "invalid TOML", "line 4")


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ("settings = 1", "settings"),
        ('fail_on = "never"', "fail_on"),
        ('lockfile = ""', "lockfile"),
        ("lockfile = ['a']", "lockfile"),
    ],
)
def test_t8_wrong_type_and_bad_fail_on_value_exit_2(project: Path, body: str, key: str) -> None:
    path = _pyproject(project, f"[tool.authzlock]\n{body}\n")

    with pytest.raises(ConfigError, match=key):
        load_config(project)
    _assert_config_error(_invoke("diff", "--base", "HEAD"), path, key)


def test_extra_table_that_is_not_a_table_exits_2(project: Path) -> None:
    path = _pyproject(project, '[tool]\nauthzlock = "yes"\n')

    _assert_config_error(_invoke("check"), path, "must be a table")


def test_extra_config_error_wins_over_flags(project: Path) -> None:
    path = _pyproject(project, '[tool.authzlock]\nfail_on = "never"\n')

    result = _invoke("check", "--settings", "x", "--lockfile", "other.lock")

    _assert_config_error(result, path, "fail_on")


def test_extra_help_still_shows_defaults() -> None:
    result = CliRunner().invoke(app, ["diff", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    assert "[default: any]" in result.stdout
    assert "[default: authz.lock]" in result.stdout

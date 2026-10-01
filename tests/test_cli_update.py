"""Tests for SHA-225: `authzlock update` and the shared CLI conventions.

Every test that loads a fixture project runs the CLI in a subprocess (`run_cli`), because
Django can only be set up once per process. Only T4 runs in-process: it fails before Django
is imported.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from authzlock import lockfile
from authzlock.cli import app
from authzlock.errors import EXIT_ERROR, EXIT_OK
from authzlock.model import Inventory
from harness import run_cli, run_extract

FIXTURE = "drf_viewsets"


def _expected_text(fixture: str) -> str:
    """`lockfile.dump(extract())` for `fixture`, extracted in a separate process."""
    return lockfile.dump(Inventory.from_dict(run_extract(fixture)))


def test_t1_update_writes_lockfile_matching_extract(tmp_path: Path) -> None:
    result = run_cli(["update"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_OK, result.stderr
    written = tmp_path / "authz.lock"
    assert written.is_file()
    expected = _expected_text(FIXTURE)
    assert written.read_bytes() == expected.encode("utf-8")
    routes = len(lockfile.load(expected).routes)
    assert result.stdout == f"authz.lock: {routes} routes written\n"
    assert result.stderr == ""


def test_t2_lockfile_option_creates_parent_directory(tmp_path: Path) -> None:
    result = run_cli(["update", "--lockfile", "out/authz.lock"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_OK, result.stderr
    written = tmp_path / "out" / "authz.lock"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == _expected_text(FIXTURE)
    assert not (tmp_path / "authz.lock").exists()
    assert "out/authz.lock" in result.stdout


def test_t3_settings_option_without_env_var(tmp_path: Path) -> None:
    result = run_cli(
        ["update", "--settings", "settings"],
        cwd=tmp_path,
        fixture=FIXTURE,
        env={"DJANGO_SETTINGS_MODULE": None},
    )

    assert result.returncode == EXIT_OK, result.stderr
    assert (tmp_path / "authz.lock").read_text(encoding="utf-8") == _expected_text(FIXTURE)


def test_t4_no_settings_anywhere_exits_2_with_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["update"], env={"DJANGO_SETTINGS_MODULE": None})

    assert result.exit_code == EXIT_ERROR, result.output
    assert "DJANGO_SETTINGS_MODULE" in result.stderr
    assert "--settings" in result.stderr
    assert len(result.stderr.strip().splitlines()) <= 2
    assert result.stdout == ""
    assert not (tmp_path / "authz.lock").exists()


def test_t5_unchanged_lockfile_is_not_rewritten(tmp_path: Path) -> None:
    first = run_cli(["update"], cwd=tmp_path, fixture=FIXTURE)
    assert first.returncode == EXIT_OK, first.stderr
    written = tmp_path / "authz.lock"
    # A fixed old mtime makes a rewrite visible regardless of filesystem timestamp precision.
    old = 1_000_000_000
    os.utime(written, (old, old))

    second = run_cli(["update"], cwd=tmp_path, fixture=FIXTURE)

    assert second.returncode == EXIT_OK, second.stderr
    assert written.stat().st_mtime == old
    assert second.stdout == "authz.lock: unchanged\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_t6_unwritable_path_exits_2_naming_it(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        result = run_cli(
            ["update", "--lockfile", "locked/authz.lock"], cwd=tmp_path, fixture=FIXTURE
        )
    finally:
        locked.chmod(stat.S_IRWXU)

    assert result.returncode == EXIT_ERROR, result.stdout
    assert "locked/authz.lock" in result.stderr
    assert len(result.stderr.strip().splitlines()) <= 2
    assert "Traceback" not in result.stderr
    assert not (locked / "authz.lock").exists()


def test_t7_settings_import_error_text_reaches_stderr(tmp_path: Path) -> None:
    result = run_cli(["update"], cwd=tmp_path, fixture="broken")

    assert result.returncode == EXIT_ERROR, result.stdout
    assert "boom" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "authz.lock").exists()


def test_extra_quiet_suppresses_success_output(tmp_path: Path) -> None:
    result = run_cli(["update", "--quiet"], cwd=tmp_path, fixture=FIXTURE)

    assert result.returncode == EXIT_OK, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "authz.lock").is_file()


def test_extra_python_m_authzlock_matches_console_script(tmp_path: Path) -> None:
    module = run_cli(["--version"], cwd=tmp_path)
    script = subprocess.run(
        [str(Path(sys.executable).parent / "authzlock"), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert module.returncode == EXIT_OK, module.stderr
    assert script.returncode == EXIT_OK, script.stderr
    assert module.stdout == script.stdout
    assert module.stdout.startswith("authzlock ")

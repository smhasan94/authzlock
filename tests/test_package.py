"""Packaging tests for SHA-181: T1, T4 and T5."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _base_interpreter() -> Path:
    """The interpreter this environment was created from.

    Creating a venv from inside a venv breaks on some Python builds (the nested copy of the
    binary cannot find libpython), so the fresh venv is built from the real base interpreter,
    located through the standard ``home`` key in ``pyvenv.cfg``.
    """
    if sys.prefix == sys.base_prefix:
        return Path(sys.executable)
    for line in (Path(sys.prefix) / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            home = Path(value.strip())
            for name in ("python3", "python", "python.exe"):
                if (home / name).exists():
                    return home / name
    return Path(sys.executable)


@pytest.fixture(scope="session")
def built_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the wheel and sdist once per session into a temp directory."""
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture(scope="session")
def built_wheel(built_dist: Path) -> Path:
    wheels = sorted(built_dist.glob("authzlock-*.whl"))
    assert len(wheels) == 1, list(built_dist.iterdir())
    return wheels[0]


@pytest.mark.slow
def test_t1_wheel_installs_in_fresh_venv(built_wheel: Path, tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [str(_base_interpreter()), "-m", "venv", "--clear", str(venv_dir)],
        check=True,
        capture_output=True,
    )
    python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"

    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(built_wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    result = subprocess.run(
        [str(python), "-c", "import authzlock"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_t4_build_produces_wheel_and_sdist_with_expected_contents(
    built_dist: Path, built_wheel: Path
) -> None:
    sdists = sorted(built_dist.glob("authzlock-*.tar.gz"))
    assert len(sdists) == 1, list(built_dist.iterdir())

    with zipfile.ZipFile(built_wheel) as wheel:
        names = wheel.namelist()
    assert "authzlock/cli.py" in names
    assert not any(name.startswith("tests/") for name in names), names


def test_t5_license_and_readme_have_required_content() -> None:
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "MIT License" in license_text
    assert "Copyright (c)" in license_text and "Sharukh Hasan" in license_text
    assert "authzlock" in readme

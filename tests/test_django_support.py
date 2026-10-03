"""Tests for SHA-285: Django 6.0 and 6.1 are supported, and every list of versions agrees."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

DJANGO_6 = ["6.0", "6.1"]


@pytest.fixture(scope="module")
def noxfile(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "authzlock_noxfile_django", repo_root / "noxfile.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t1_django_6_runs_on_python_312_and_313_only(noxfile: ModuleType) -> None:
    for django in DJANGO_6:
        assert django in noxfile.DJANGOS
        pythons = {py for py, dj in noxfile.SUPPORTED if dj == django}
        assert pythons == {"3.12", "3.13"}, django
    assert len(noxfile.SUPPORTED) == 15


def test_t3_classifiers_match_supported_djangos(repo_root: Path, noxfile: ModuleType) -> None:
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    versions = set(re.findall(r'"Framework :: Django :: ([0-9.]+)"', text))
    assert versions == set(noxfile.DJANGOS)


def test_t4_readme_compatibility_table_matches_supported(
    repo_root: Path, noxfile: ModuleType
) -> None:
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    section = text.split("## Compatibility", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    header = [cell.strip() for cell in rows[0].strip("|").split("|")]
    assert header[0] == "Python"
    djangos = [cell.removeprefix("Django ") for cell in header[1:]]
    assert djangos == noxfile.DJANGOS

    cells = set()
    for row in rows[2:]:
        python, *marks = (cell.strip() for cell in row.strip("|").split("|"))
        assert len(marks) == len(djangos), row
        assert set(marks) <= {"yes", "no"}, row
        cells |= {(python, dj) for dj, mark in zip(djangos, marks, strict=True) if mark == "yes"}
    assert cells == set(noxfile.SUPPORTED)

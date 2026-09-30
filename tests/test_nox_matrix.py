"""nox matrix tests for SHA-183: T2, T6, T7 and one extra check."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def noxfile(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("authzlock_noxfile", repo_root / "noxfile.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tests_sessions(names: list[str]) -> set[str]:
    return {name for name in names if name.startswith("tests(")}


def test_t2_session_list_matches_supported_matrix(
    noxfile: ModuleType, nox_session_names: list[str]
) -> None:
    expected = {f"tests(python='{py}', django='{dj}')" for py, dj in noxfile.SUPPORTED}
    assert len(expected) == 11
    assert _tests_sessions(nox_session_names) == expected


def test_t6_no_unsupported_pairs(noxfile: ModuleType, nox_session_names: list[str]) -> None:
    pattern = re.compile(r"^tests\(python='(?P<py>[0-9.]+)', django='(?P<dj>[0-9.]+)'\)$")
    for name in _tests_sessions(nox_session_names):
        match = pattern.match(name)
        assert match, name
        assert match["py"] in noxfile.PYTHONS, name
        assert match["dj"] in noxfile.DJANGOS, name
        assert not (match["dj"] == "4.2" and match["py"] == "3.13"), name


def test_t7_development_md_commands_name_real_sessions(
    repo_root: Path, nox_session_names: list[str]
) -> None:
    text = (repo_root / "DEVELOPMENT.md").read_text(encoding="utf-8")
    commands_section = text.split("## Commands", 1)[1].split("\n## ", 1)[0]
    requested = re.findall(r'^nox -s "?([^"\n]+?)"?$', commands_section, flags=re.MULTILINE)
    assert requested, "DEVELOPMENT.md must document at least one nox -s command"

    base_names = {name.split("(", 1)[0].split("-", 1)[0] for name in nox_session_names}
    for command in requested:
        assert command in nox_session_names or command in base_names, command


def test_extra_supported_covers_every_django_and_python(noxfile: ModuleType) -> None:
    pythons = {py for py, _ in noxfile.SUPPORTED}
    djangos = {dj for _, dj in noxfile.SUPPORTED}
    assert pythons == set(noxfile.PYTHONS)
    assert djangos == set(noxfile.DJANGOS)

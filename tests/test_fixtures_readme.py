"""Fixture layout tests for SHA-183: T5."""

from __future__ import annotations

from pathlib import Path


def test_t5_fixture_readme_present(repo_root: Path) -> None:
    readme = repo_root / "tests" / "fixtures" / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    assert "one per view style" in text
    assert "DJANGO_SETTINGS_MODULE" in text

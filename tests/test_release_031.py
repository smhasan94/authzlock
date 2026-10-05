"""Tests for the 0.3.1 release: the changelog section."""

from __future__ import annotations

import re
from pathlib import Path


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"CHANGELOG.md has no '## {heading}' section"
    return match.group(1)


def test_changelog_031_section_complete(repo_root: Path) -> None:
    text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[0\.3\.1\] - \d{4}-\d{2}-\d{2}$", text, re.M), "no dated 0.3.1"
    assert text.index("## [Unreleased]") < text.index("## [0.3.1]") < text.index("## [0.3.0]")

    released = _section(text, "[0.3.1]")
    assert "README is shorter" in released

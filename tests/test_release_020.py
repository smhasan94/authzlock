"""Tests for the 0.2.0 release: the changelog section and the pre-commit revs."""

from __future__ import annotations

import re
from pathlib import Path


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"CHANGELOG.md has no '## {heading}' section"
    return match.group(1)


def test_changelog_020_section_complete(repo_root: Path) -> None:
    text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[0\.2\.0\] - \d{4}-\d{2}-\d{2}$", text, re.M), "no dated 0.2.0"
    assert text.index("## [Unreleased]") < text.index("## [0.2.0]") < text.index("## [0.1.0]")

    released = _section(text, "[0.2.0]")
    for item in (
        "[tool.authzlock]",
        "--format sarif",
        "--ignore-path",
        "authzlock gen-tests",
        "Rule R9",
        "FastAPI",
        "0 equivalent",
        "`v1` Action tag moves",
    ):
        assert item in released, item


def test_install_docs_name_the_020_pre_commit_rev(repo_root: Path) -> None:
    for page in ("README.md", "docs/pre-commit.md"):
        text = (repo_root / page).read_text(encoding="utf-8")
        assert re.findall(r"rev: (v\d+\.\d+\.\d+)", text) == ["v0.2.0"], page

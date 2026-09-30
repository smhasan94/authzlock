"""pytest configuration tests for SHA-183: T4."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess


def test_t4_failing_test_fails_run(
    tmp_path: Path, repo_root: Path, run_python: Callable[..., CompletedProcess[str]]
) -> None:
    test_file = tmp_path / "test_fails.py"
    test_file.write_text("def test_it() -> None:\n    assert False\n", encoding="utf-8")

    result = run_python(
        [
            "-m",
            "pytest",
            "-c",
            str(repo_root / "pyproject.toml"),
            "-p",
            "no:cacheprovider",
            str(test_file),
        ]
    )

    assert result.returncode == 1, result.stdout
    assert "1 failed" in result.stdout

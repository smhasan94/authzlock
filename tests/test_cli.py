"""CLI tests for SHA-181: T2, T3, T6 and one extra check."""

from __future__ import annotations

import re
from importlib import metadata

from typer.testing import CliRunner

import authzlock
from authzlock.cli import app

runner = CliRunner()


def test_t2_version_flag_prints_version_and_exits_zero() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert re.fullmatch(r"authzlock \d+\.\d+\.\d+\S*\n", result.output)
    assert result.output.strip() == f"authzlock {authzlock.__version__}"


def test_t3_no_args_prints_help_and_exits_zero() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_t6_unknown_command_exits_nonzero_and_names_it() -> None:
    result = runner.invoke(app, ["nope"])

    assert result.exit_code != 0
    assert "nope" in result.output


def test_extra_metadata_version_matches_dunder_version() -> None:
    assert metadata.version("authzlock") == authzlock.__version__

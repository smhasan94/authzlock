"""nox sessions for authzlock. Run `nox` to run everything CI runs."""

from __future__ import annotations

import nox

RUFF = "ruff==0.16.9"

nox.options.sessions = ["lint", "typecheck"]


@nox.session
def lint(session: nox.Session) -> None:
    """Run ruff lint and formatting checks."""
    session.install(RUFF)
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session
def typecheck(session: nox.Session) -> None:
    """Run mypy in strict mode on the package."""
    session.install("-e", ".[dev]")
    session.run("mypy", "src/authzlock")

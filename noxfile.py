"""nox sessions for authzlock. Run `nox` to run everything CI runs."""

from __future__ import annotations

import nox

RUFF = "ruff==0.16.9"

PYTHONS = ["3.10", "3.11", "3.12", "3.13"]
DJANGOS = ["4.2", "5.1", "5.2"]
# Django 4.2 does not support Python 3.13.
UNSUPPORTED = {("3.13", "4.2")}
SUPPORTED = [(py, dj) for dj in DJANGOS for py in PYTHONS if (py, dj) not in UNSUPPORTED]

# DRF 3.16 is the first release that supports Django 5.2.
DRF = "djangorestframework>=3.16"

nox.options.sessions = ["lint", "typecheck", "tests"]
nox.options.default_venv_backend = "uv|virtualenv"


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


@nox.session
@nox.parametrize("python,django", SUPPORTED)
def tests(session: nox.Session, django: str) -> None:
    """Run the test suite against one Python and Django combination."""
    session.install("-e", ".[dev]")
    session.install(f"django~={django}.0", DRF)
    session.env["AUTHZLOCK_DJANGO"] = django
    session.run("pytest", *session.posargs)

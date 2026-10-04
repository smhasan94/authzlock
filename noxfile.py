"""nox sessions for authzlock. Run `nox` to run everything CI runs."""

from __future__ import annotations

import nox

RUFF = "ruff==0.16.9"

PYTHONS = ["3.10", "3.11", "3.12", "3.13"]
DJANGOS = ["4.2", "5.1", "5.2", "6.0", "6.1"]
# Django 4.2 does not support Python 3.13; Django 6.0 and newer need Python 3.12.
UNSUPPORTED = {
    ("3.13", "4.2"),
    ("3.10", "6.0"),
    ("3.11", "6.0"),
    ("3.10", "6.1"),
    ("3.11", "6.1"),
}
SUPPORTED = [(py, dj) for dj in DJANGOS for py in PYTHONS if (py, dj) not in UNSUPPORTED]

# DRF 3.16 is the first release that supports Django 5.2.
DRF = "djangorestframework>=3.16"

# The oldest supported DRF gets one cell of its own; it does not support Django 5.x.
DRF_MIN = "djangorestframework==3.14.*"
MIN_DRF_DJANGO = "4.2"
# drf-nested-routers 0.95 needs DRF 3.15; 0.94 is the last release that supports DRF 3.14.
NESTED_ROUTERS_MIN = "drf-nested-routers==0.94.*"

# The oldest supported FastAPI, from before included routers were resolved lazily, so the
# extractor's fallback for a flat `app.routes` stays tested.
FASTAPI_MIN = "fastapi==0.100.*"
FASTAPI_MIN_DJANGO = "5.2"

nox.options.sessions = ["lint", "typecheck", "tests", "tests_min_drf", "tests_min_fastapi"]
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


@nox.session(python="3.12")
def tests_min_drf(session: nox.Session) -> None:
    """Run the test suite against the oldest supported DRF on Django 4.2."""
    session.install("-e", ".[dev]")
    session.install(f"django~={MIN_DRF_DJANGO}.0", DRF_MIN, NESTED_ROUTERS_MIN)
    session.env["AUTHZLOCK_DJANGO"] = MIN_DRF_DJANGO
    session.env["AUTHZLOCK_DRF"] = "3.14"
    session.run("pytest", *session.posargs)


@nox.session(python="3.12")
def tests_min_fastapi(session: nox.Session) -> None:
    """Run the test suite against the oldest supported FastAPI."""
    session.install("-e", ".[dev]")
    session.install(f"django~={FASTAPI_MIN_DJANGO}.0", DRF, FASTAPI_MIN)
    session.env["AUTHZLOCK_DJANGO"] = FASTAPI_MIN_DJANGO
    session.run("pytest", *session.posargs)

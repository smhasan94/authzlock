"""Errors raised by authzlock and the exit codes the CLI maps them to."""

from __future__ import annotations

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2


class AuthzlockError(Exception):
    """Base class for errors that authzlock reports to the user as plain text."""


class ProjectLoadError(AuthzlockError):
    """The target Django project could not be loaded."""


class LockfileError(AuthzlockError):
    """The lockfile could not be read or written."""


class ConfigError(AuthzlockError):
    """The `[tool.authzlock]` table in `pyproject.toml` could not be read or is invalid."""


class GitError(AuthzlockError):
    """A git command needed to read the base lockfile failed."""

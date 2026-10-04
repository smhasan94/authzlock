"""Read the `[tool.authzlock]` table from the nearest `pyproject.toml`.

The table is optional. Keys: `settings` (Django settings module), `lockfile` (path relative
to the directory holding `pyproject.toml`) and `fail_on` (`any` or `loosened`). Command-line
flags and `DJANGO_SETTINGS_MODULE` take precedence; the CLI applies that rule.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from authzlock.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PYPROJECT = "pyproject.toml"
KEYS = ("fail_on", "lockfile", "settings")
FAIL_ON_VALUES = ("any", "loosened")


@dataclass(frozen=True)
class Config:
    """Values from `[tool.authzlock]`; None for every key that is absent."""

    settings: str | None = None
    lockfile: Path | None = None
    fail_on: str | None = None
    path: Path | None = None


def find_pyproject(start: Path) -> Path | None:
    """The first `pyproject.toml` in `start` or one of its parents, or None."""
    start = start.resolve()
    for directory in (start, *start.parents):
        candidate = directory / PYPROJECT
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> Config:
    """Read `[tool.authzlock]` from the nearest `pyproject.toml` at or above `start`.

    `start` defaults to the current directory. No file, or a file without the table, gives
    an all-None `Config`. Anything else that is wrong raises `ConfigError`.
    """
    path = find_pyproject(start if start is not None else Path.cwd())
    if path is None:
        return Config()
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}.") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}.") from exc

    tool = data.get("tool", {})
    table = tool.get("authzlock") if isinstance(tool, dict) else None
    if table is None:
        return Config(path=path)
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [tool.authzlock] must be a table.")

    for key in table:
        if key not in KEYS:
            raise ConfigError(
                f"{path}: unknown key {key!r} in [tool.authzlock].\n"
                f"Allowed keys: {', '.join(KEYS)}."
            )
    values: dict[str, str] = {}
    for key, value in table.items():
        if not isinstance(value, str) or not value:
            raise ConfigError(
                f"{path}: [tool.authzlock] {key} must be a non-empty string, got {value!r}."
            )
        values[key] = value
    fail_on = values.get("fail_on")
    if fail_on is not None and fail_on not in FAIL_ON_VALUES:
        raise ConfigError(
            f"{path}: [tool.authzlock] fail_on must be 'any' or 'loosened', got {fail_on!r}."
        )
    lockfile = values.get("lockfile")
    return Config(
        settings=values.get("settings"),
        lockfile=path.parent / lockfile if lockfile is not None else None,
        fail_on=fail_on,
        path=path,
    )

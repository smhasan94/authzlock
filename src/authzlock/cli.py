"""Command-line entry point for authzlock.

Conventions shared by every command: `--settings` overrides `DJANGO_SETTINGS_MODULE`,
`--lockfile` defaults to `authz.lock` in the current directory, `--quiet` silences the
success line. Errors are one or two plain lines on stderr and exit with code 2.

`[tool.authzlock]` in the nearest `pyproject.toml` supplies `settings`, `lockfile` and
`fail_on` when neither a flag nor (for settings) `DJANGO_SETTINGS_MODULE` gives one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from authzlock import __version__, gitutil, lockfile
from authzlock.config import load_config
from authzlock.diff import compute as compute_diff
from authzlock.django_loader import SETTINGS_ENV
from authzlock.errors import (
    EXIT_ERROR,
    EXIT_MISMATCH,
    AuthzlockError,
    LockfileError,
    ProjectLoadError,
)
from authzlock.model import Inventory
from authzlock.render import build_report, render_check, render_markdown, render_text

DEFAULT_LOCKFILE = Path("authz.lock")

app = typer.Typer(
    name="authzlock",
    help="An authorization lockfile for Django and Django REST Framework.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)

SettingsOption = Annotated[
    str | None,
    typer.Option(
        "--settings",
        metavar="MODULE",
        help="Django settings module to load. Overrides DJANGO_SETTINGS_MODULE.",
        show_default=False,
    ),
]
LockfileOption = Annotated[
    Path,
    typer.Option(
        "--lockfile",
        metavar="PATH",
        help="Path of the lockfile, relative to the current directory.",
        dir_okay=False,
    ),
]
QuietOption = Annotated[
    bool,
    typer.Option("--quiet", "-q", help="Print nothing on success."),
]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"authzlock {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the authzlock version and exit.",
    ),
) -> None:
    """Read access rules from a Django project and keep them in a committed lockfile."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


class OutputFormat(str, Enum):
    text = "text"
    markdown = "markdown"


class FailOn(str, Enum):
    any = "any"
    loosened = "loosened"


@dataclass(frozen=True)
class _Options:
    """Option values after applying flags, `DJANGO_SETTINGS_MODULE` and `[tool.authzlock]`."""

    settings: str | None
    lockfile: Path
    fail_on: FailOn
    # The pyproject.toml the settings module came from, when it came from there.
    settings_config: Path | None = None


def _display_path(path: Path) -> Path:
    """`path` relative to the current directory when possible, for messages."""
    try:
        return Path(os.path.relpath(path))
    except ValueError:
        return path


def _given(ctx: typer.Context, name: str) -> bool:
    """True if parameter `name` was set on the command line rather than left at its default.

    Compared by name: Typer 0.12 uses click's `ParameterSource`, later versions a private copy.
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name not in ("DEFAULT", "DEFAULT_MAP")


def _effective_options(
    ctx: typer.Context,
    settings: str | None,
    lockfile_path: Path,
    fail_on: FailOn = FailOn.any,
) -> _Options:
    """Resolve options: a flag wins, then `DJANGO_SETTINGS_MODULE` (settings only), then
    `[tool.authzlock]`, then the built-in default. Raises `ConfigError` for a bad table.
    """
    config = load_config()
    settings_config = None
    if settings is None and not os.environ.get(SETTINGS_ENV) and config.settings is not None:
        settings, settings_config = config.settings, config.path
    if config.lockfile is not None and not _given(ctx, "lockfile_path"):
        lockfile_path = _display_path(config.lockfile)
    if config.fail_on is not None and not _given(ctx, "fail_on"):
        fail_on = FailOn(config.fail_on)
    return _Options(settings, lockfile_path, fail_on, settings_config)


def _options_or_exit(
    ctx: typer.Context,
    settings: str | None,
    lockfile_path: Path,
    fail_on: FailOn = FailOn.any,
) -> _Options:
    try:
        return _effective_options(ctx, settings, lockfile_path, fail_on)
    except AuthzlockError as exc:
        _fail(exc)


def _fail(exc: AuthzlockError) -> NoReturn:
    """Report `exc` on stderr as plain text and exit with the error code."""
    typer.echo(f"authzlock: {exc}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _extract_or_exit(options: _Options) -> Inventory:
    """Load the Django project and extract its inventory, exiting with code 2 on failure."""
    from authzlock.django_loader import load_project
    from authzlock.extract import extract

    try:
        load_project(options.settings)
        return extract()
    except ProjectLoadError as exc:
        if options.settings_config is not None:
            exc = ProjectLoadError(
                f"{exc}\nThe settings module is set in [tool.authzlock] in "
                f"{options.settings_config}."
            )
        _fail(exc)
    except AuthzlockError as exc:
        _fail(exc)


def _load_lockfile(path: Path) -> Inventory:
    """Read and parse the lockfile at `path`; every failure is a `LockfileError`."""
    if not path.exists():
        raise LockfileError(
            f"{path} not found.\nRun `authzlock update` to create it, then commit it."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        raise LockfileError(f"cannot read {path}: {reason}.") from exc
    try:
        return lockfile.load(text)
    except LockfileError as exc:
        raise LockfileError(f"{path}: {exc}") from exc


def _write_if_changed(path: Path, text: str) -> bool:
    """Write `text` to `path` unless it already holds exactly that; True if written."""
    data = text.encode("utf-8")
    try:
        if path.is_file() and path.read_bytes() == data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise LockfileError(
            f"cannot write {path}: {reason}.\n"
            "Check that the directory is writable, or pass --lockfile with another path."
        ) from exc
    return True


@app.command()
def update(
    ctx: typer.Context,
    settings: SettingsOption = None,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Extract the project's access rules and write them to the lockfile."""
    options = _options_or_exit(ctx, settings, lockfile_path)
    lockfile_path = options.lockfile
    inventory = _extract_or_exit(options)
    try:
        written = _write_if_changed(lockfile_path, lockfile.dump(inventory))
    except LockfileError as exc:
        _fail(exc)
    if quiet:
        return
    if written:
        count = len(inventory.routes)
        noun = "route" if count == 1 else "routes"
        typer.echo(f"{lockfile_path}: {count} {noun} written")
    else:
        typer.echo(f"{lockfile_path}: unchanged")


@app.command()
def check(
    ctx: typer.Context,
    settings: SettingsOption = None,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Compare the project's access rules with the lockfile; exit 1 if they differ."""
    options = _options_or_exit(ctx, settings, lockfile_path)
    lockfile_path = options.lockfile
    try:
        base = _load_lockfile(lockfile_path)
    except LockfileError as exc:
        _fail(exc)
    current = _extract_or_exit(options)
    diff = compute_diff(base, current)
    if diff.is_empty:
        if not quiet:
            typer.echo(f"{lockfile_path}: up to date")
        return
    typer.echo(render_check(diff, lockfile=str(lockfile_path)), nl=False)
    raise typer.Exit(EXIT_MISMATCH)


def _base_inventory(ref: str, lockfile_path: Path) -> tuple[Inventory | None, str]:
    """The lockfile committed at `ref` (None if absent) and its repository-relative path."""
    cwd = Path.cwd()
    root = gitutil.repo_root(cwd)
    relative = gitutil.repo_relative(lockfile_path, cwd=cwd, root=root)
    text = gitutil.read_at_ref(ref, relative, cwd=cwd)
    if text is None:
        return None, relative
    try:
        return lockfile.load(text), relative
    except LockfileError as exc:
        raise LockfileError(f"{ref}:{relative}: {exc}") from exc


@app.command()
def diff(
    ctx: typer.Context,
    base: Annotated[
        str,
        typer.Option(
            "--base",
            metavar="REF",
            help="Git ref whose committed lockfile is the old side, for example origin/main.",
            show_default=False,
        ),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Output format.", case_sensitive=False),
    ] = OutputFormat.text,
    fail_on: Annotated[
        FailOn,
        typer.Option(
            "--fail-on",
            help="Exit 1 on any change, or only when a route is loosened.",
            case_sensitive=False,
        ),
    ] = FailOn.any,
    settings: SettingsOption = None,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Compare the lockfile committed at a git ref with the project's current access rules."""
    options = _options_or_exit(ctx, settings, lockfile_path, fail_on)
    try:
        base_inventory, relative = _base_inventory(base, options.lockfile)
    except AuthzlockError as exc:
        _fail(exc)
    current = _extract_or_exit(options)
    report = build_report(
        compute_diff(base_inventory or Inventory(), current),
        ref=base,
        lockfile=relative,
        base_found=base_inventory is not None,
    )
    if not (report.diff.is_empty and quiet):
        render = render_markdown if output_format is OutputFormat.markdown else render_text
        typer.echo(render(report), nl=False)
    if options.fail_on is FailOn.loosened:
        failed = report.count("loosened") > 0
    else:
        failed = not report.diff.is_empty
    if failed:
        raise typer.Exit(EXIT_MISMATCH)

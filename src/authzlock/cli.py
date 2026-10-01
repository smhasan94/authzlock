"""Command-line entry point for authzlock.

Conventions shared by every command: `--settings` overrides `DJANGO_SETTINGS_MODULE`,
`--lockfile` defaults to `authz.lock` in the current directory, `--quiet` silences the
success line. Errors are one or two plain lines on stderr and exit with code 2.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from authzlock import __version__, gitutil, lockfile
from authzlock.diff import compute as compute_diff
from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, AuthzlockError, LockfileError
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


def _fail(exc: AuthzlockError) -> NoReturn:
    """Report `exc` on stderr as plain text and exit with the error code."""
    typer.echo(f"authzlock: {exc}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _extract_or_exit(settings: str | None) -> Inventory:
    """Load the Django project and extract its inventory, exiting with code 2 on failure."""
    from authzlock.django_loader import load_project
    from authzlock.extract import extract

    try:
        load_project(settings)
        return extract()
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
    settings: SettingsOption = None,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Extract the project's access rules and write them to the lockfile."""
    inventory = _extract_or_exit(settings)
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
    settings: SettingsOption = None,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Compare the project's access rules with the lockfile; exit 1 if they differ."""
    try:
        base = _load_lockfile(lockfile_path)
    except LockfileError as exc:
        _fail(exc)
    current = _extract_or_exit(settings)
    diff = compute_diff(base, current)
    if diff.is_empty:
        if not quiet:
            typer.echo(f"{lockfile_path}: up to date")
        return
    typer.echo(render_check(diff, lockfile=str(lockfile_path)), nl=False)
    raise typer.Exit(EXIT_MISMATCH)


class OutputFormat(str, Enum):
    text = "text"
    markdown = "markdown"


class FailOn(str, Enum):
    any = "any"
    loosened = "loosened"


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
    try:
        base_inventory, relative = _base_inventory(base, lockfile_path)
    except AuthzlockError as exc:
        _fail(exc)
    current = _extract_or_exit(settings)
    report = build_report(
        compute_diff(base_inventory or Inventory(), current),
        ref=base,
        lockfile=relative,
        base_found=base_inventory is not None,
    )
    if not (report.diff.is_empty and quiet):
        render = render_markdown if output_format is OutputFormat.markdown else render_text
        typer.echo(render(report), nl=False)
    if fail_on is FailOn.loosened:
        failed = report.count("loosened") > 0
    else:
        failed = not report.diff.is_empty
    if failed:
        raise typer.Exit(EXIT_MISMATCH)

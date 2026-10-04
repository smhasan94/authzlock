"""Command-line entry point for authzlock.

Conventions shared by every command: `--settings` overrides `DJANGO_SETTINGS_MODULE`,
`--app` overrides `AUTHZLOCK_APP`, `--lockfile` defaults to `authz.lock` in the current
directory, `--quiet` silences the success line. Errors are one or two plain lines on stderr
and exit with code 2.

`[tool.authzlock]` in the nearest `pyproject.toml` supplies `settings`, `app`, `lockfile` and
`fail_on` when neither a flag nor (for settings and app) an environment variable gives one.
`--framework auto` picks the framework from the first of those three tiers that names a
project: an app means FastAPI, a settings module Django.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from authzlock import __version__, gitutil, lockfile
from authzlock.config import Config, load_config
from authzlock.diff import compute as compute_diff
from authzlock.django_loader import SETTINGS_ENV
from authzlock.errors import (
    EXIT_ERROR,
    EXIT_MISMATCH,
    AuthzlockError,
    LockfileError,
    ProjectLoadError,
)
from authzlock.extract.fastapi import SOURCE as DEPENDENCY_SOURCE
from authzlock.fastapi_loader import APP_ENV
from authzlock.gen_tests import DEFAULT_OUTPUT as DEFAULT_TESTS_OUTPUT
from authzlock.gen_tests import generate as generate_tests
from authzlock.ignore import apply as apply_ignore
from authzlock.model import IgnoreList, Inventory
from authzlock.render import (
    DiffReport,
    build_report,
    render_check,
    render_json,
    render_markdown,
    render_text,
    to_document,
)

DEFAULT_LOCKFILE = Path("authz.lock")

app = typer.Typer(
    name="authzlock",
    help="An authorization lockfile for Django, Django REST Framework and FastAPI.",
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
AppOption = Annotated[
    str | None,
    typer.Option(
        "--app",
        metavar="MODULE:ATTR",
        help="FastAPI application to load, for example main:app. Overrides AUTHZLOCK_APP.",
        show_default=False,
    ),
]


class Framework(str, Enum):
    auto = "auto"
    django = "django"
    fastapi = "fastapi"


FrameworkOption = Annotated[
    Framework,
    typer.Option(
        "--framework",
        help="Framework of the project. auto: FastAPI when an app is given, Django when a "
        "settings module is.",
        case_sensitive=False,
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
IgnorePathOption = Annotated[
    list[str] | None,
    typer.Option(
        "--ignore-path",
        metavar="PREFIX",
        help="Leave out routes whose URL pattern starts with PREFIX. Repeatable; replaces the "
        "list recorded in the lockfile.",
        show_default=False,
    ),
]
IgnoreViewOption = Annotated[
    list[str] | None,
    typer.Option(
        "--ignore-view",
        metavar="PREFIX",
        help="Leave out routes whose view is in module PREFIX. Repeatable; replaces the list "
        "recorded in the lockfile.",
        show_default=False,
    ),
]
NoIgnoreOption = Annotated[
    bool,
    typer.Option("--no-ignore", help="Clear the ignore list recorded in the lockfile."),
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
    """Read access rules from a Django or FastAPI project and keep them in a committed lockfile."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


class OutputFormat(str, Enum):
    text = "text"
    markdown = "markdown"
    json = "json"
    sarif = "sarif"


class FailOn(str, Enum):
    any = "any"
    loosened = "loosened"


@dataclass(frozen=True)
class _Options:
    """Option values after applying flags and `[tool.authzlock]`; the project to load is
    resolved by `_project` only when a command extracts."""

    lockfile: Path
    fail_on: FailOn
    framework: Framework = Framework.auto
    settings: str | None = None
    app: str | None = None
    config: Config = Config()


@dataclass(frozen=True)
class _Project:
    """The project to extract: Django with `settings`, or FastAPI with `app`."""

    framework: Framework
    settings: str | None = None
    app: str | None = None
    # The pyproject.toml the settings module or app came from, when it came from there.
    config_path: Path | None = None


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
    lockfile_path: Path,
    fail_on: FailOn = FailOn.any,
    *,
    framework: Framework = Framework.auto,
    settings: str | None = None,
    app: str | None = None,
) -> _Options:
    """Resolve options: a flag wins, then `[tool.authzlock]`, then the built-in default.
    Raises `ConfigError` for a bad table.
    """
    config = load_config()
    if config.lockfile is not None and not _given(ctx, "lockfile_path"):
        lockfile_path = _display_path(config.lockfile)
    if config.fail_on is not None and not _given(ctx, "fail_on"):
        fail_on = FailOn(config.fail_on)
    return _Options(lockfile_path, fail_on, framework, settings, app, config)


def _options_or_exit(
    ctx: typer.Context,
    lockfile_path: Path,
    fail_on: FailOn = FailOn.any,
    *,
    framework: Framework = Framework.auto,
    settings: str | None = None,
    app: str | None = None,
) -> _Options:
    try:
        return _effective_options(
            ctx, lockfile_path, fail_on, framework=framework, settings=settings, app=app
        )
    except AuthzlockError as exc:
        _fail(exc)


def _project(options: _Options) -> _Project:
    """The project to extract. The tiers (flags, environment, `[tool.authzlock]`) are tried
    in order; `--framework auto` takes the first tier that names an app or a settings module
    and refuses one that names both. Raises `ProjectLoadError` when nothing names a project.
    """
    config = options.config
    tiers = (
        ("on the command line", options.app, options.settings, None),
        ("in the environment", os.environ.get(APP_ENV), os.environ.get(SETTINGS_ENV), None),
        (f"in [tool.authzlock] in {config.path}", config.app, config.settings, config.path),
    )
    framework = options.framework
    for where, app, settings, origin in tiers:
        if framework is Framework.django and settings:
            return _Project(Framework.django, settings=settings, config_path=origin)
        if framework is Framework.fastapi and app:
            return _Project(Framework.fastapi, app=app, config_path=origin)
        if framework is not Framework.auto:
            continue
        if app and settings:
            raise ProjectLoadError(
                f"Both an app ({app}) and a settings module ({settings}) are set {where}.\n"
                "Pass --framework fastapi or --framework django to choose one."
            )
        if app:
            return _Project(Framework.fastapi, app=app, config_path=origin)
        if settings:
            return _Project(Framework.django, settings=settings, config_path=origin)
    if framework is Framework.django:
        # load_project explains how to name a settings module.
        return _Project(Framework.django)
    if framework is Framework.fastapi:
        raise ProjectLoadError(
            f"No FastAPI app given.\nSet {APP_ENV} or pass --app, for example --app main:app."
        )
    raise ProjectLoadError(
        "No Django settings module or FastAPI app given.\n"
        f"Set {SETTINGS_ENV} or pass --settings for Django; set {APP_ENV} or pass --app "
        "for FastAPI."
    )


def _fail(exc: AuthzlockError) -> NoReturn:
    """Report `exc` on stderr as plain text and exit with the error code."""
    typer.echo(f"authzlock: {exc}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _extract_or_exit(options: _Options) -> Inventory:
    """Load the Django project or FastAPI app and extract its inventory, exiting with code 2
    on failure."""
    project: _Project | None = None
    try:
        project = _project(options)
        if project.framework is Framework.fastapi:
            from authzlock.extract.fastapi import extract_app
            from authzlock.fastapi_loader import load_app

            assert project.app is not None
            return extract_app(load_app(project.app))
        from authzlock.django_loader import load_project
        from authzlock.extract import extract

        load_project(project.settings)
        return extract()
    except ProjectLoadError as exc:
        if project is not None and project.config_path is not None:
            what = "app" if project.framework is Framework.fastapi else "settings module"
            exc = ProjectLoadError(
                f"{exc}\nThe {what} is set in [tool.authzlock] in {project.config_path}."
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


def _write_if_changed(path: Path, text: str, *, option: str = "--lockfile") -> bool:
    """Write `text` to `path` unless it already holds exactly that; True if written.

    `option` is the flag the error hint suggests for choosing another path.
    """
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
            f"Check that the directory is writable, or pass {option} with another path."
        ) from exc
    return True


def _recorded_ignore(path: Path) -> IgnoreList:
    """The ignore list of the lockfile at `path`; empty when the file is missing or unreadable,
    since `update` is how such a file gets repaired."""
    try:
        return _load_lockfile(path).ignore if path.is_file() else IgnoreList()
    except LockfileError:
        return IgnoreList()


def _ignore_for_update(
    path: Path, paths: list[str] | None, views: list[str] | None, clear: bool
) -> IgnoreList:
    """The list `update` writes: cleared, replaced by the options, or kept from `path`."""
    if clear and (paths or views):
        _fail(AuthzlockError("--no-ignore cannot be combined with --ignore-path or --ignore-view."))
    if clear:
        return IgnoreList()
    if paths or views:
        return IgnoreList.of(paths or (), views or ())
    return _recorded_ignore(path)


@app.command()
def update(
    ctx: typer.Context,
    settings: SettingsOption = None,
    app_name: AppOption = None,
    framework: FrameworkOption = Framework.auto,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    ignore_path: IgnorePathOption = None,
    ignore_view: IgnoreViewOption = None,
    no_ignore: NoIgnoreOption = False,
    quiet: QuietOption = False,
) -> None:
    """Extract the project's access rules and write them to the lockfile."""
    options = _options_or_exit(
        ctx, lockfile_path, framework=framework, settings=settings, app=app_name
    )
    lockfile_path = options.lockfile
    ignore = _ignore_for_update(lockfile_path, ignore_path, ignore_view, no_ignore)
    inventory = apply_ignore(_extract_or_exit(options), ignore)
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
    app_name: AppOption = None,
    framework: FrameworkOption = Framework.auto,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Compare the project's access rules with the lockfile; exit 1 if they differ."""
    options = _options_or_exit(
        ctx, lockfile_path, framework=framework, settings=settings, app=app_name
    )
    lockfile_path = options.lockfile
    try:
        base = _load_lockfile(lockfile_path)
    except LockfileError as exc:
        _fail(exc)
    current = apply_ignore(_extract_or_exit(options), base.ignore)
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


def _render_document(report: DiffReport, output_format: OutputFormat) -> str:
    """The JSON or SARIF document for `report`, with view locations from the loaded project."""
    from authzlock.locate import locate_entries
    from authzlock.sarif import render_sarif

    locations = locate_entries(report.entries, gitutil.repo_root(Path.cwd()))
    document = to_document(report, locations)
    return render_sarif(document) if output_format is OutputFormat.sarif else render_json(document)


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
    app_name: AppOption = None,
    framework: FrameworkOption = Framework.auto,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    quiet: QuietOption = False,
) -> None:
    """Compare the lockfile committed at a git ref with the project's current access rules."""
    options = _options_or_exit(
        ctx, lockfile_path, fail_on, framework=framework, settings=settings, app=app_name
    )
    try:
        base_inventory, relative = _base_inventory(base, options.lockfile)
        base_ignore = base_inventory.ignore if base_inventory is not None else IgnoreList()
        # The working tree's list wins, so a pull request that changes it is diffed with it.
        if options.lockfile.is_file():
            ignore = _load_lockfile(options.lockfile).ignore
        else:
            ignore = base_ignore
    except AuthzlockError as exc:
        _fail(exc)
    current = apply_ignore(_extract_or_exit(options), ignore)
    report = build_report(
        compute_diff(base_inventory or Inventory(), current),
        ref=base,
        lockfile=relative,
        base_found=base_inventory is not None,
        ignore=(base_ignore, ignore),
    )
    if output_format in (OutputFormat.json, OutputFormat.sarif):
        # A machine-readable document is printed even with --quiet, so a redirect to a file
        # always yields a valid document.
        typer.echo(_render_document(report, output_format), nl=False)
    elif not (report.diff.is_empty and quiet):
        render = render_markdown if output_format is OutputFormat.markdown else render_text
        typer.echo(render(report), nl=False)
    if options.fail_on is FailOn.loosened:
        failed = report.count("loosened") > 0
    else:
        failed = not report.diff.is_empty
    if failed:
        raise typer.Exit(EXIT_MISMATCH)


@app.command("gen-tests")
def gen_tests(
    ctx: typer.Context,
    lockfile_path: LockfileOption = DEFAULT_LOCKFILE,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            metavar="PATH",
            help="Path of the generated pytest module, relative to the current directory.",
            dir_okay=False,
        ),
    ] = Path(DEFAULT_TESTS_OUTPUT),
    quiet: QuietOption = False,
) -> None:
    """Write pytest tests asserting that anonymous requests to protected routes are refused.

    Reads only the lockfile; the project is loaded when the generated tests run.
    """
    options = _options_or_exit(ctx, lockfile_path)
    try:
        inventory = _load_lockfile(options.lockfile)
        if any(route.permission_source == DEPENDENCY_SOURCE for route in inventory.routes):
            raise LockfileError(
                f"{options.lockfile} was written from a FastAPI app; "
                "gen-tests supports Django lockfiles only."
            )
        text, summary = generate_tests(
            inventory.routes, lockfile=options.lockfile.as_posix(), output=output.as_posix()
        )
        written = _write_if_changed(output, text, option="--output")
    except LockfileError as exc:
        _fail(exc)
    if quiet:
        return
    typer.echo(f"{output}: {summary}" if written else f"{output}: unchanged ({summary})")

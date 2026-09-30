"""Command-line entry point for authzlock."""

from __future__ import annotations

import typer

from authzlock import __version__

app = typer.Typer(
    name="authzlock",
    help="An authorization lockfile for Django and Django REST Framework.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)


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

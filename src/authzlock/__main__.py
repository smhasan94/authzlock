"""`python -m authzlock`: the same CLI as the `authzlock` console script."""

from __future__ import annotations

from authzlock.cli import app

app(prog_name="authzlock")

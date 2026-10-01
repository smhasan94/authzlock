"""Read a file as committed at a git ref, for `authzlock diff`.

Everything goes through the `git` executable in a subprocess. Failures raise `GitError`
with git's own message, so the CLI can print them as plain two-line errors.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from authzlock.errors import GitError


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError(
            "git not found.\n`authzlock diff` reads the base lockfile with git; install git "
            "or put it on PATH."
        ) from exc


def _first_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[0].strip() if lines else "no error message"


def repo_root(cwd: Path) -> Path:
    """The top-level directory of the git working tree that contains `cwd`."""
    result = _run(["rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0:
        raise GitError(
            f"not a git repository: {cwd}.\n"
            "`authzlock diff` reads the base lockfile with git; run it inside a git checkout."
        )
    return Path(result.stdout.strip())


def repo_relative(path: Path, *, cwd: Path, root: Path) -> str:
    """`path` (relative to `cwd`) as a forward-slash path relative to the repository root."""
    absolute = (cwd / path).resolve()
    try:
        return absolute.relative_to(root.resolve()).as_posix()
    except ValueError:
        raise GitError(
            f"{path} is outside the git repository at {root}.\n"
            "Pass a --lockfile path inside the repository."
        ) from None


def read_at_ref(ref: str, path: str, *, cwd: Path) -> str | None:
    """The text of `path` (repository-relative) at `ref`, or None if `ref` has no such file.

    Raises `GitError` when `ref` does not name a commit or git fails otherwise.
    """
    if not ref or ref.startswith("-"):
        raise GitError(f"invalid git ref {ref!r}.\nA ref must not be empty or start with '-'.")
    verify = _run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)
    if verify.returncode != 0:
        # Ask git again for a message that names the ref; `--quiet` prints nothing.
        detail = _run(["show", f"{ref}:{path}"], cwd)
        raise GitError(
            f"git ref {ref!r} not found: {_first_line(detail.stderr)}\n"
            "Fetch it first, for example `git fetch origin main`, or pass another --base."
        )
    commit = verify.stdout.strip()
    listing = _run(["ls-tree", "-z", "--name-only", "--full-tree", commit, "--", path], cwd)
    if listing.returncode != 0:
        raise GitError(f"cannot list {path} at {ref}: {_first_line(listing.stderr)}")
    if path not in listing.stdout.split("\0"):
        return None
    shown = _run(["show", f"{commit}:{path}"], cwd)
    if shown.returncode != 0:
        raise GitError(f"cannot read {path} at {ref}: {_first_line(shown.stderr)}")
    return shown.stdout

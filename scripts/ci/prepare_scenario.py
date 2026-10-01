"""Set up the docs/scenario.md project as a git repository for the action end-to-end workflow.

    python scripts/ci/prepare_scenario.py DEST [--loosen]

Copies `tests/fixtures/scenario_loosen` to DEST (which must not exist), adds its golden
lockfile as `authz.lock`, and commits everything in a new git repository, so `HEAD` is the
base the action compares with. With `--loosen` it then applies the scenario's pull request
without committing it: `permission_classes = [IsAuthenticated, IsOwner]` becomes
`permission_classes = [IsAuthenticated]` in `billing/views.py`.

The repository has no remote, so the action must be given `base-ref: HEAD`. Exits 0 on
success and 2 on any error.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "scenario_loosen"
VIEWS = Path("billing") / "views.py"
ORIGINAL = "permission_classes = [IsAuthenticated, IsOwner]"
LOOSENED = "permission_classes = [IsAuthenticated]"
# A fixed identity, so the commit works on runners and machines without a git config.
GIT_IDENTITY = ("-c", "user.name=authzlock e2e", "-c", "user.email=e2e@authzlock.invalid")


class PrepareError(Exception):
    pass


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *GIT_IDENTITY, *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise PrepareError(f"git {' '.join(args)} failed: {result.stderr.strip()}")


def loosen(repo: Path) -> None:
    """Apply the scenario's one-line change to `billing/views.py`."""
    path = repo / VIEWS
    text = path.read_text(encoding="utf-8")
    if text.count(ORIGINAL) != 1:
        raise PrepareError(f"{ORIGINAL!r} is not in {path} exactly once")
    path.write_text(text.replace(ORIGINAL, LOOSENED), encoding="utf-8")


def prepare(dest: Path, *, loosened: bool) -> None:
    if dest.exists():
        raise PrepareError(f"{dest} already exists")
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("*.expected", "__pycache__"))
    shutil.copyfile(FIXTURE / "authz.lock.expected", dest / "authz.lock")
    (dest / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(dest, "init", "--quiet")
    _git(dest, "add", "--all")
    _git(dest, "commit", "--quiet", "--message", "scenario_loosen fixture and lockfile")
    if loosened:
        loosen(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prepare_scenario.py", description=__doc__.split("\n")[0])
    parser.add_argument("dest", type=Path)
    parser.add_argument("--loosen", action="store_true", help="Apply the loosening edit.")
    args = parser.parse_args(argv)
    try:
        prepare(args.dest, loosened=args.loosen)
    except (PrepareError, OSError) as exc:
        print(f"prepare_scenario: {exc}", file=sys.stderr)
        return 2
    state = "with the loosening edit applied" if args.loosen else "unchanged"
    print(f"prepare_scenario: {args.dest} committed, {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

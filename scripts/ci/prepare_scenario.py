"""Set up the docs/scenario.md project as a git repository for the action end-to-end workflow.

    python scripts/ci/prepare_scenario.py DEST [--loosen] [--fastapi]

Copies `tests/fixtures/scenario_loosen` to DEST (which must not exist), adds its golden
lockfile as `authz.lock`, and commits everything in a new git repository, so `HEAD` is the
base the action compares with. With `--loosen` it then applies the scenario's pull request
without committing it: `permission_classes = [IsAuthenticated, IsOwner]` becomes
`permission_classes = [IsAuthenticated]` in `billing/views.py`.

With `--fastapi` the project is `tests/fixtures/fastapi_basic` instead, and `--loosen` drops
the `HTTPBearer` dependency from `token_info` in `main.py`, which rule R10 labels loosened.

The repository has no remote, so the action must be given `base-ref: HEAD`. Exits 0 on
success and 2 on any error.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


@dataclass(frozen=True)
class Scenario:
    """A fixture project and the one-line edit that loosens it."""

    fixture: str
    path: Path
    original: str
    loosened: str


DJANGO = Scenario(
    "scenario_loosen",
    Path("billing") / "views.py",
    "permission_classes = [IsAuthenticated, IsOwner]",
    "permission_classes = [IsAuthenticated]",
)
FASTAPI = Scenario(
    "fastapi_basic",
    Path("main.py"),
    "def token_info(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> None:",
    "def token_info() -> None:",
)
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


def loosen(repo: Path, scenario: Scenario = DJANGO) -> None:
    """Apply the scenario's one-line change."""
    path = repo / scenario.path
    text = path.read_text(encoding="utf-8")
    if text.count(scenario.original) != 1:
        raise PrepareError(f"{scenario.original!r} is not in {path} exactly once")
    path.write_text(text.replace(scenario.original, scenario.loosened), encoding="utf-8")


def prepare(dest: Path, *, loosened: bool, scenario: Scenario = DJANGO) -> None:
    if dest.exists():
        raise PrepareError(f"{dest} already exists")
    fixture = FIXTURES / scenario.fixture
    shutil.copytree(fixture, dest, ignore=shutil.ignore_patterns("*.expected", "__pycache__"))
    shutil.copyfile(fixture / "authz.lock.expected", dest / "authz.lock")
    (dest / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(dest, "init", "--quiet")
    _git(dest, "add", "--all")
    _git(dest, "commit", "--quiet", "--message", f"{scenario.fixture} fixture and lockfile")
    if loosened:
        loosen(dest, scenario)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prepare_scenario.py", description=__doc__.split("\n")[0])
    parser.add_argument("dest", type=Path)
    parser.add_argument("--loosen", action="store_true", help="Apply the loosening edit.")
    parser.add_argument("--fastapi", action="store_true", help="Use the FastAPI fixture.")
    args = parser.parse_args(argv)
    try:
        prepare(args.dest, loosened=args.loosen, scenario=FASTAPI if args.fastapi else DJANGO)
    except (PrepareError, OSError) as exc:
        print(f"prepare_scenario: {exc}", file=sys.stderr)
        return 2
    state = "with the loosening edit applied" if args.loosen else "unchanged"
    print(f"prepare_scenario: {args.dest} committed, {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

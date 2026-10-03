"""Check that the `v1` action tag points at the same commit as a release tag.

    python scripts/ci/check_v1_tag.py RELEASE_TAG

Run in a clone that has both tags, for example `python scripts/ci/check_v1_tag.py v0.1.0`.
Exits 0 when `v1` and RELEASE_TAG resolve to the same commit, 1 when they differ or `v1` is
missing, and 2 when RELEASE_TAG is missing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

ACTION_TAG = "v1"


def _commit(tag: str) -> str | None:
    """The commit `tag` points at, or None when the tag does not exist."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("release_tag", help="the release tag, for example v0.1.0")
    args = parser.parse_args(argv)

    release = _commit(args.release_tag)
    if release is None:
        print(f"error: tag {args.release_tag} does not exist", file=sys.stderr)
        return 2
    action = _commit(ACTION_TAG)
    if action is None:
        print(f"error: tag {ACTION_TAG} does not exist; expected it at {release}", file=sys.stderr)
        return 1
    if action != release:
        print(
            f"error: {ACTION_TAG} points at {action} but {args.release_tag} points at {release}",
            file=sys.stderr,
        )
        return 1
    print(f"{ACTION_TAG} and {args.release_tag} point at {release}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

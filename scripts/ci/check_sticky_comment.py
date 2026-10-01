"""Check that a pull request has exactly one authzlock comment, with the expected body.

    python scripts/ci/check_sticky_comment.py --repo OWNER/NAME --pr N --comment-id ID
        --expect TEXT [--expect TEXT]...

Used by the `sticky-comment` job of `.github/workflows/action-e2e.yml`. It lists the pull
request's comments with the action's own helper (`gh api`, token from `GH_TOKEN`) and
checks that exactly one starts with the `<!-- authzlock -->` marker, that it is comment ID
(the one both upserts reported), and that its body contains every TEXT. Exits 0 when all
checks pass, 1 when one fails, 2 when the comments cannot be listed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any

MARKER = "<!-- authzlock -->"


def problems(
    comments: Sequence[Mapping[str, Any]], *, comment_id: int, expected: Sequence[str]
) -> list[str]:
    """Every failed check, as a message; empty when the pull request passes."""
    marked = [c for c in comments if str(c.get("body", "")).lstrip().startswith(MARKER)]
    if len(marked) != 1:
        found = [f"expected exactly one authzlock comment, found {len(marked)}"]
        found.extend(f"  comment {c['id']}" for c in marked)
        return found
    comment = marked[0]
    found = []
    if int(comment["id"]) != comment_id:
        found.append(f"the authzlock comment is {comment['id']}, expected {comment_id}")
    body = str(comment.get("body", ""))
    found.extend(
        f"the comment body does not contain {text!r}" for text in expected if text not in body
    )
    return found


def main(argv: list[str] | None = None) -> int:
    from authzlock._github import GithubError, list_comments

    parser = argparse.ArgumentParser(prog="check_sticky_comment.py")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--comment-id", required=True, type=int)
    parser.add_argument("--expect", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        comments = list_comments(args.repo, args.pr)
    except GithubError as exc:
        print(f"check_sticky_comment: {exc}", file=sys.stderr)
        return 2
    found = problems(comments, comment_id=args.comment_id, expected=args.expect)
    for message in found:
        print(f"check_sticky_comment: {message}", file=sys.stderr)
    if found:
        return 1
    print(
        f"check_sticky_comment: {args.repo}#{args.pr} has one authzlock comment "
        f"({args.comment_id}) with the expected body"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

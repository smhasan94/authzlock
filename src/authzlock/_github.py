"""Helpers the GitHub Action (`action.yml`) runs as `python -m authzlock._github`.

Three subcommands, each reading the markdown report `authzlock diff --format markdown`
wrote to a file:

- `upsert-comment --repo OWNER/NAME --pr N --body-file PATH` posts the report as a pull
  request comment, or updates the newest comment that starts with `MARKDOWN_MARKER`, so a
  pull request keeps one authzlock comment however often it is pushed to. Older marker
  comments are left as they are. It talks to GitHub only through `gh api`, which reads
  the token from `GH_TOKEN`.
- `outputs --report PATH` writes the `summary` and `loosened` step outputs.
- `gate --report PATH --fail-on-loosened true|false` exits 1 when the flag is true and the
  summary line counts at least one loosened route.

Exit codes follow the CLI: 0 ok, 1 the gate failed, 2 error. This module is private: its
interface is the action, not a public API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from authzlock.errors import EXIT_ERROR, EXIT_MISMATCH, EXIT_OK
from authzlock.render import MARKDOWN_MARKER, SUMMARY_LABELS

# GitHub rejects issue comments longer than 65536 characters.
MAX_BODY = 65536
HEADING = "### authzlock: access-control changes"
NO_CHANGES_BODY = f"{MARKDOWN_MARKER}\n{HEADING}\n\nauthzlock found no access-control changes.\n"
TRUNCATED = "\n\n_The report was truncated to fit in a comment; the full diff is in the job log._\n"
SUMMARY_RE = re.compile(
    r"^" + r", ".join(rf"(\d+) {re.escape(label)}" for label in SUMMARY_LABELS) + r"$",
    re.MULTILINE,
)


class GithubError(Exception):
    """A `gh` call failed or the report could not be used."""


def comment_body(markdown: str) -> str:
    """The comment text for a report: the report itself, marked and cut to GitHub's limit."""
    if not markdown.strip():
        return NO_CHANGES_BODY
    body = markdown if markdown.startswith(MARKDOWN_MARKER) else f"{MARKDOWN_MARKER}\n{markdown}"
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - len(TRUNCATED)].rstrip() + TRUNCATED
    return body


def parse_summary(markdown: str) -> dict[str, int]:
    """The five counts of the report's summary line, keyed by label."""
    matches = SUMMARY_RE.findall(markdown)
    if len(matches) != 1:
        raise GithubError(
            f"expected one summary line in the authzlock report, found {len(matches)}.\n"
            "Check the output of `authzlock diff` above."
        )
    return {label: int(count) for label, count in zip(SUMMARY_LABELS, matches[0], strict=True)}


def should_fail(*, fail_on_loosened: bool, loosened: int) -> bool:
    """True when the job must fail: the flag is set and a route was loosened."""
    return fail_on_loosened and loosened > 0


def find_comment(comments: Sequence[Mapping[str, Any]]) -> int | None:
    """Id of the newest comment whose body starts with the marker, or None.

    "Starts with" rather than "contains" so that a reply quoting the comment is never
    taken for it. Newest is by `created_at`, then by id.
    """
    marked = [c for c in comments if str(c.get("body", "")).lstrip().startswith(MARKDOWN_MARKER)]
    if not marked:
        return None
    newest = max(marked, key=lambda c: (str(c.get("created_at", "")), int(c["id"])))
    return int(newest["id"])


def _gh_api(args: Sequence[str], payload: Mapping[str, Any] | None = None) -> Any:
    command = ["gh", "api", *args]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GithubError(
            "gh is not installed.\nThe action needs the GitHub CLI, which GitHub-hosted "
            "runners provide."
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GithubError(f"`gh api {' '.join(args)}` failed: {detail}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def list_comments(repo: str, pr: int) -> list[dict[str, Any]]:
    """Every comment on the pull request, across all pages."""
    pages = _gh_api(["--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments"])
    return [comment for page in pages or [] for comment in page]


def upsert_comment(repo: str, pr: int, body: str) -> tuple[str, int]:
    """Update the newest marker comment or create one; returns the action taken and the id."""
    existing = find_comment(list_comments(repo, pr))
    if existing is None:
        created = _gh_api(
            ["-X", "POST", f"repos/{repo}/issues/{pr}/comments", "--input", "-"], {"body": body}
        )
        return "created", int(created["id"])
    _gh_api(
        ["-X", "PATCH", f"repos/{repo}/issues/comments/{existing}", "--input", "-"],
        {"body": body},
    )
    return "updated", existing


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GithubError(f"cannot read {path}: {exc.strerror or exc}.") from exc


def _flag(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        raise GithubError(f"fail-on-loosened must be true or false, not {value!r}.")
    return lowered == "true"


def _write_outputs(values: Mapping[str, str]) -> None:
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lines)
    else:
        sys.stdout.write(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m authzlock._github")
    commands = parser.add_subparsers(dest="command", required=True)
    upsert = commands.add_parser("upsert-comment", help="Create or update the PR comment.")
    upsert.add_argument("--repo", required=True)
    upsert.add_argument("--pr", required=True, type=int)
    upsert.add_argument("--body-file", required=True, type=Path)
    outputs = commands.add_parser("outputs", help="Write the summary step outputs.")
    outputs.add_argument("--report", required=True, type=Path)
    gate = commands.add_parser("gate", help="Fail when a route is loosened.")
    gate.add_argument("--report", required=True, type=Path)
    gate.add_argument("--fail-on-loosened", required=True)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "upsert-comment":
        action, comment_id = upsert_comment(args.repo, args.pr, comment_body(_read(args.body_file)))
        print(f"authzlock: {action} comment {comment_id} on {args.repo}#{args.pr}")
        return EXIT_OK
    counts = parse_summary(_read(args.report))
    if args.command == "outputs":
        summary = ", ".join(f"{counts[label]} {label}" for label in SUMMARY_LABELS)
        _write_outputs({"summary": summary, "loosened": str(counts["loosened"])})
        return EXIT_OK
    loosened = counts["loosened"]
    if should_fail(fail_on_loosened=_flag(args.fail_on_loosened), loosened=loosened):
        noun = "route" if loosened == 1 else "routes"
        print(
            f"::error::authzlock: {loosened} {noun} loosened. Review the access-control "
            "changes, or set fail-on-loosened: false to report without failing."
        )
        return EXIT_MISMATCH
    print(f"authzlock: {loosened} loosened; not failing")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except GithubError as exc:
        print(f"authzlock: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

"""Check an `authzlock diff --format markdown` report in the action end-to-end workflow.

    python scripts/ci/assert_summary.py REPORT [--summary LINE] [--row LABEL
        [--row-contains TEXT]...] [--contains TEXT]...

- `--summary LINE`: the report has exactly one summary line and it equals LINE, for example
  `1 loosened, 0 tightened, 0 added, 0 removed, 0 changed-unknown`.
- `--row LABEL`: the report has exactly one table row whose first cell is LABEL; the row is
  printed so the job log shows it. Each `--row-contains TEXT` must appear in that row.
- `--contains TEXT`: TEXT appears somewhere in the report, ignoring case.

Exits 0 when every check passes, 1 when one fails (each failure is printed to stderr), and
2 on a usage error or an unreadable report. It parses the report itself rather than
importing authzlock, so it checks the action's output independently of the code under test.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LABELS = ("loosened", "tightened", "added", "removed", "changed-unknown")
SUMMARY_RE = re.compile(
    r"^" + r", ".join(rf"\d+ {re.escape(label)}" for label in LABELS) + r"$", re.MULTILINE
)


def summary_lines(report: str) -> list[str]:
    return [match.group(0) for match in SUMMARY_RE.finditer(report)]


def rows(report: str, label: str) -> list[str]:
    return [line for line in report.splitlines() if line.startswith(f"| {label} |")]


def problems(
    report: str,
    *,
    summary: str | None,
    row: str | None,
    row_contains: list[str],
    contains: list[str],
) -> list[str]:
    """Every failed check, as a message; empty when the report passes."""
    found: list[str] = []
    if summary is not None:
        lines = summary_lines(report)
        if len(lines) != 1:
            found.append(f"expected one summary line, found {len(lines)}")
        elif lines[0] != summary:
            found.append(f"summary line is {lines[0]!r}, expected {summary!r}")
        else:
            print(f"summary: {lines[0]}")
    if row is not None:
        matches = rows(report, row)
        if len(matches) != 1:
            found.append(f"expected one {row!r} row, found {len(matches)}")
        else:
            print(f"row: {matches[0]}")
            found.extend(
                f"the {row!r} row does not contain {text!r}"
                for text in row_contains
                if text not in matches[0]
            )
    lowered = report.lower()
    for text in contains:
        if text.lower() in lowered:
            print(f"contains: {text}")
        else:
            found.append(f"the report does not contain {text!r}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assert_summary.py", description=__doc__.split("\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary")
    parser.add_argument("--row")
    parser.add_argument("--row-contains", action="append", default=[])
    parser.add_argument("--contains", action="append", default=[])
    args = parser.parse_args(argv)
    if args.row_contains and args.row is None:
        print("assert_summary: --row-contains needs --row", file=sys.stderr)
        return 2
    try:
        report = args.report.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"assert_summary: cannot read {args.report}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    found = problems(
        report,
        summary=args.summary,
        row=args.row,
        row_contains=args.row_contains,
        contains=args.contains,
    )
    for message in found:
        print(f"assert_summary: {message}", file=sys.stderr)
    if found:
        print(f"--- {args.report} ---\n{report}", file=sys.stderr)
        return 1
    print("assert_summary: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

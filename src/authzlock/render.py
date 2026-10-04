"""Text and markdown output for the CLI.

`render_check(diff)` is what `authzlock check` prints when the lockfile and the project
disagree: one group each for added, removed and changed routes, one line per route key,
`field: old -> new` lines under each changed route, short groups for custom permission
registry changes, then the hint to run `authzlock update`. Empty groups are left out.
Lines are never wrapped.

`render_text(report)` and `render_markdown(report)` are what `authzlock diff` prints for a
`DiffReport` built with `build_report`. Both end with the summary line, the six counts in
`SUMMARY_LABELS` order, for example `1 loosened, 0 tightened, 2 added, 0 removed,
0 changed-unknown, 0 equivalent`, on a line of its own so CI scripts can parse it. The
markdown starts with `MARKDOWN_MARKER`, a hidden comment the GitHub Action uses to find its
own comment.

`to_document(report, locations)` is the machine-readable form of a report, described in
`docs/diff-json.md`; `render_json` prints it and `sarif.render_sarif` maps it to SARIF.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from authzlock import __version__
from authzlock.classify import ClassifiedRoute, Label, classify_diff
from authzlock.diff import Diff, FieldChange
from authzlock.model import IgnoreList, Route

_INDENT = "  "


def render_check(diff: Diff, *, lockfile: str = "authz.lock") -> str:
    """The text `check` prints for a non-empty `diff`; `lockfile` names the file in the hint."""
    lines = [f"{lockfile} is out of date."]
    _group(lines, "added", (route.key() for route in diff.added))
    _group(lines, "removed", (route.key() for route in diff.removed))
    if diff.changed:
        lines.append("changed:")
        for change in diff.changed:
            lines.append(f"{_INDENT}{change.key()}")
            lines.extend(_field_lines(change.fields))
    _group(lines, "custom permissions added", (p.path for p in diff.custom_permissions_added))
    _group(lines, "custom permissions removed", (p.path for p in diff.custom_permissions_removed))
    if diff.custom_permissions_changed:
        lines.append("custom permissions changed:")
        for entry in diff.custom_permissions_changed:
            lines.append(f"{_INDENT}{entry.path}")
            lines.extend(_field_lines(entry.fields))
    lines.extend(["", f"To fix: run `authzlock update` and commit {lockfile}."])
    return "\n".join(lines) + "\n"


def _group(lines: list[str], header: str, items: Iterable[str]) -> None:
    entries = [f"{_INDENT}{item}" for item in items]
    if entries:
        lines.append(f"{header}:")
        lines.extend(entries)


def _field_lines(changes: Iterable[FieldChange]) -> list[str]:
    return [
        f"{_INDENT * 2}{change.field}: {format_value(change.old)} -> {format_value(change.new)}"
        for change in changes
    ]


def format_value(value: Any) -> str:
    """One-line form of a lockfile value: YAML-like scalars, `[a, b]` lists, `{k: v}` maps."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Quote only what would otherwise be unreadable or span lines.
        return json.dumps(value) if value == "" or "\n" in value else value
    if isinstance(value, Mapping):
        items = ", ".join(f"{key}: {format_value(value[key])}" for key in sorted(value))
        return f"{{{items}}}"
    if isinstance(value, list | tuple):
        return f"[{', '.join(format_value(item) for item in value)}]"
    return str(value)


# authzlock diff -----------------------------------------------------------------------------

# Order of the summary counts and of the groups in both outputs.
SUMMARY_LABELS: tuple[Label, ...] = (
    "loosened",
    "tightened",
    "added",
    "removed",
    "changed-unknown",
    "equivalent",
)
# Labels shown in the open markdown table; the others go in collapsed sections.
_OPEN_LABELS: frozenset[Label] = frozenset({"loosened", "tightened"})
MARKDOWN_MARKER = "<!-- authzlock -->"
NO_CHANGES = "no changes"
_LABEL_WIDTH = max(len(label) for label in SUMMARY_LABELS)


@dataclass(frozen=True, kw_only=True)
class DiffReport:
    """A diff against a base ref, classified and ready to render.

    `lockfile` is the repository-relative lockfile path read at `ref`; `base_found` is
    False when the ref has no lockfile there and every route is reported as added.
    """

    ref: str
    lockfile: str
    base_found: bool
    diff: Diff
    entries: tuple[ClassifiedRoute, ...]
    # (base lockfile's list, list applied to the current project).
    ignore: tuple[IgnoreList, IgnoreList] = (IgnoreList(), IgnoreList())

    @property
    def ignore_changed(self) -> tuple[IgnoreList, IgnoreList] | None:
        """Both ignore lists when they differ, None when they are the same."""
        return self.ignore if self.ignore[0] != self.ignore[1] else None

    def count(self, label: Label) -> int:
        return sum(1 for entry in self.entries if entry.classification.label == label)

    def summary(self) -> str:
        return ", ".join(f"{self.count(label)} {label}" for label in SUMMARY_LABELS)

    def group(self, label: Label) -> list[ClassifiedRoute]:
        return [entry for entry in self.entries if entry.classification.label == label]

    @property
    def note(self) -> str | None:
        if self.base_found:
            return None
        return (
            f"base ref has no authz.lock ({self.ref}:{self.lockfile}); "
            "every route is reported as added"
        )

    @property
    def notes(self) -> list[str]:
        """Every note to print above the changes, one line each."""
        notes = [self.note] if self.note else []
        if self.ignore_changed is not None:
            notes.append(ignore_note(self.ref, *self.ignore_changed))
        return notes


def ignore_note(ref: str, old: IgnoreList, new: IgnoreList) -> str:
    """The note shown when the base lockfile's ignore list differs from the current one."""
    return (
        f"ignore list changed from {_describe_ignore(old)} at {ref} to "
        f"{_describe_ignore(new)}; routes it drops or restores are reported as "
        "removed or added"
    )


def _describe_ignore(ignore: IgnoreList) -> str:
    """`paths [a/, b/], views [x]`, leaving out an empty list, or `nothing`."""
    parts = [
        f"{name} [{', '.join(values)}]"
        for name, values in (("paths", ignore.paths), ("views", ignore.views))
        if values
    ]
    return ", ".join(parts) or "nothing"


def build_report(
    diff: Diff,
    *,
    ref: str,
    lockfile: str,
    base_found: bool,
    ignore: tuple[IgnoreList, IgnoreList] = (IgnoreList(), IgnoreList()),
) -> DiffReport:
    """Classify `diff` and bundle it with where the base lockfile came from."""
    return DiffReport(
        ref=ref,
        lockfile=lockfile,
        base_found=base_found,
        diff=diff,
        entries=classify_diff(diff),
        ignore=ignore,
    )


def _access(route: Route) -> list[str]:
    """The access fields of an added or removed route, as `field: value` texts."""
    parts = []
    if route.permission_classes is not None:
        parts.append(f"permission_classes: {format_value(route.permission_classes)}")
    if route.django_auth is not None:
        parts.append(f"django_auth: {format_value(route.django_auth)}")
    return parts


def _field_texts(entry: ClassifiedRoute) -> list[str]:
    if entry.change is None:
        return _access(entry.route)
    return [
        f"{fc.field}: {format_value(fc.old)} -> {format_value(fc.new)}"
        for fc in entry.change.fields
    ]


def _registry_lines(diff: Diff) -> list[tuple[str, str, str]]:
    """(kind, dotted path, detail) for every custom permission registry change."""
    rows = [("added", entry.path, "") for entry in diff.custom_permissions_added]
    rows += [("removed", entry.path, "") for entry in diff.custom_permissions_removed]
    rows += [
        (
            "changed",
            entry.path,
            "; ".join(
                f"{fc.field}: {format_value(fc.old)} -> {format_value(fc.new)}"
                for fc in entry.fields
            ),
        )
        for entry in diff.custom_permissions_changed
    ]
    return rows


def render_text(report: DiffReport) -> str:
    """Plain text: one line per route, grouped by label, then the summary line.

    Each line is `<label> <METHODS> <path> -> <view>  <field changes>`, with the rule and
    reason in parentheses for changed routes. An empty diff prints `no changes`.
    """
    lines: list[str] = []
    for note in report.notes:
        lines.append(f"note: {note}")
    if report.notes:
        lines.append("")
    if report.diff.is_empty:
        return "\n".join([*lines, NO_CHANGES]) + "\n"
    for label in SUMMARY_LABELS:
        group = report.group(label)
        if not group:
            continue
        for entry in group:
            line = f"{label:<{_LABEL_WIDTH}} {entry.key}"
            details = "; ".join(_field_texts(entry))
            if details:
                line += f"  {details}"
            if entry.change is not None:
                line += f"  ({entry.classification.reason})"
            lines.append(line)
        lines.append("")
    registry = _registry_lines(report.diff)
    if registry:
        for kind, path, detail in registry:
            lines.append(f"custom-permission {kind} {path}" + (f"  {detail}" if detail else ""))
        lines.append("")
    lines.append(report.summary())
    return "\n".join(lines) + "\n"


def _code(value: str) -> str:
    """`value` as an inline code span that is safe inside a markdown table cell."""
    value = value.replace("|", "\\|")
    fence = "``" if "`" in value else "`"
    pad = " " if fence == "``" else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def _md_field(field: str, old: Any, new: Any) -> str:
    return f"{_code(field)}: {_code(format_value(old))} → {_code(format_value(new))}"


def _md_detail(entry: ClassifiedRoute) -> str:
    if entry.change is None:
        parts = [_code(part) for part in _access(entry.route)]
    else:
        parts = [_code(entry.classification.reason)]
        parts += [_md_field(fc.field, fc.old, fc.new) for fc in entry.change.fields]
    return "<br>".join(parts)


_TABLE_HEAD = ["| Change | Methods | Path | View | Details |", "|---|---|---|---|---|"]


def _md_rows(entries: Iterable[ClassifiedRoute]) -> list[str]:
    return [
        f"| {entry.classification.label} | {','.join(entry.route.methods)} "
        f"| {_code(entry.route.path)} | {_code(entry.route.view)} | {_md_detail(entry)} |"
        for entry in entries
    ]


def render_markdown(report: DiffReport) -> str:
    """Markdown for a pull request comment.

    Layout: the hidden marker, a heading, the optional note, the summary line, a table of
    loosened and tightened routes, then one collapsed `<details>` section each for added,
    removed, changed-unknown and equivalent routes and for custom permission registry
    changes.
    """
    lines = [MARKDOWN_MARKER, "### authzlock: access-control changes", ""]
    for note in report.notes:
        lines.extend([f"> **Note:** {note}.", ""])
    lines.extend([report.summary(), ""])
    if report.diff.is_empty:
        lines.append(f"No access-control changes against {_code(report.ref)}.")
        return "\n".join(lines) + "\n"
    open_entries = [entry for entry in report.entries if entry.classification.label in _OPEN_LABELS]
    open_entries.sort(key=lambda entry: SUMMARY_LABELS.index(entry.classification.label))
    if open_entries:
        lines.extend([*_TABLE_HEAD, *_md_rows(open_entries), ""])
    for label in SUMMARY_LABELS:
        group = report.group(label)
        if label in _OPEN_LABELS or not group:
            continue
        noun = "route" if len(group) == 1 else "routes"
        lines.extend(
            [
                f"<details><summary>{len(group)} {label} {noun}</summary>",
                "",
                *_TABLE_HEAD,
                *_md_rows(group),
                "",
                "</details>",
                "",
            ]
        )
    registry = _registry_lines(report.diff)
    if registry:
        lines.extend(
            [
                f"<details><summary>{len(registry)} custom permission registry "
                f"{'change' if len(registry) == 1 else 'changes'}</summary>",
                "",
                "| Change | Class | Details |",
                "|---|---|---|",
                *(
                    f"| {kind} | {_code(path)} | {_code(detail) if detail else ''} |"
                    for kind, path, detail in registry
                ),
                "",
                "</details>",
                "",
            ]
        )
    return "\n".join(lines).rstrip("\n") + "\n"


# Machine-readable output ----------------------------------------------------------------

DOCUMENT_SCHEMA_VERSION = 1
# Route fields that identify a route; every other lockfile field is listed under `fields`
# for an added or removed route.
_IDENTITY_FIELDS = ("path", "view", "methods")

# (repository-relative file, line) of a route's view.
Location = tuple[str, int]


def _plain(value: Any) -> Any:
    """`value` with tuples as lists and mappings as dicts, ready for JSON."""
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    return value


def _json_fields(changes: Iterable[tuple[str, Any, Any]]) -> list[dict[str, Any]]:
    return [{"field": name, "old": _plain(old), "new": _plain(new)} for name, old, new in changes]


def _route_fields(entry: ClassifiedRoute) -> list[dict[str, Any]]:
    """Changed fields of a changed route; every non-identity field of an added or removed one."""
    if entry.change is not None:
        return _json_fields((fc.field, fc.old, fc.new) for fc in entry.change.fields)
    added = entry.classification.label == "added"
    return _json_fields(
        (name, None, value) if added else (name, value, None)
        for name, value in entry.route.to_dict().items()
        if name not in _IDENTITY_FIELDS
    )


def _change(entry: ClassifiedRoute, location: Location) -> dict[str, Any]:
    return {
        "label": entry.classification.label,
        "rule": entry.classification.rule,
        "reason": entry.classification.reason,
        "route": {
            "key": entry.key,
            "path": entry.route.path,
            "methods": list(entry.route.methods),
            "view": entry.route.view,
        },
        "fields": _route_fields(entry),
        "location": {"file": location[0], "line": location[1]},
    }


def to_document(report: DiffReport, locations: Mapping[str, Location]) -> dict[str, Any]:
    """The report as a JSON-ready dict with a fixed key order; see `docs/diff-json.md`.

    `locations` maps route keys to where their view is defined; a route without an entry
    is reported at the lockfile, line 1.
    """
    fallback: Location = (report.lockfile, 1)
    diff = report.diff
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "tool": {"name": "authzlock", "version": __version__},
        "base": {
            "ref": report.ref,
            "lockfile": report.lockfile,
            "lockfile_found": report.base_found,
        },
        "ignore": {
            "base": _ignore_lists(report.ignore[0]),
            "current": _ignore_lists(report.ignore[1]),
            "changed": report.ignore_changed is not None,
        },
        "summary": {label.replace("-", "_"): report.count(label) for label in SUMMARY_LABELS},
        "changes": [_change(entry, locations.get(entry.key, fallback)) for entry in report.entries],
        "custom_permissions": {
            "added": [entry.path for entry in diff.custom_permissions_added],
            "removed": [entry.path for entry in diff.custom_permissions_removed],
            "changed": [
                {
                    "path": entry.path,
                    "fields": _json_fields((fc.field, fc.old, fc.new) for fc in entry.fields),
                }
                for entry in diff.custom_permissions_changed
            ],
        },
    }


def _ignore_lists(ignore: IgnoreList) -> dict[str, list[str]]:
    return {"paths": list(ignore.paths), "views": list(ignore.views)}


def render_json(document: Mapping[str, Any]) -> str:
    """`document` as indented JSON with a trailing newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

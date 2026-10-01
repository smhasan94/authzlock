"""Plain-text output for the CLI.

`render_check(diff)` is what `authzlock check` prints when the lockfile and the project
disagree: one group each for added, removed and changed routes, one line per route key,
`field: old -> new` lines under each changed route, short groups for custom permission
registry changes, then the hint to run `authzlock update`. Empty groups are left out.
Lines are never wrapped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from authzlock.diff import Diff, FieldChange

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

"""Find where a route's view is defined, for `authzlock diff --format json|sarif`.

Locations are resolved at diff time from the loaded project and never stored in the
lockfile. A view is located by importing the longest importable module prefix of its
dotted path, walking the remaining attributes, unwrapping decorators and asking `inspect`
for the source file and first line. Anything that cannot be located that way, or whose
source is outside the repository, gets no location; the caller falls back to the lockfile.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from authzlock.classify import ClassifiedRoute
from authzlock.render import Location


def _resolve(dotted: str) -> Any:
    """The object named by `dotted`, or None when no module prefix imports or an attribute
    is missing."""
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            target: Any = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for attribute in parts[split:]:
            target = getattr(target, attribute, None)
            if target is None:
                return None
        return target
    return None


def locate(view: str, root: Path) -> Location | None:
    """Repository-relative, forward-slash file and first line of `view`, or None."""
    try:
        target = _resolve(view)
        if target is None:
            return None
        target = inspect.unwrap(target)
        source = inspect.getsourcefile(target)
        _, line = inspect.getsourcelines(target)
    except Exception:  # noqa: BLE001 - importing project code can raise anything
        return None
    if source is None:
        return None
    try:
        relative = Path(source).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return relative.as_posix(), max(line, 1)


def locate_entries(entries: Iterable[ClassifiedRoute], root: Path) -> dict[str, Location]:
    """Locations by route key for every entry except removed routes, whose view may no
    longer exist; entries that cannot be located are left out."""
    found: dict[str, Location] = {}
    for entry in entries:
        if entry.classification.label == "removed":
            continue
        location = locate(entry.route.view, root)
        if location is not None:
            found[entry.key] = location
    return found

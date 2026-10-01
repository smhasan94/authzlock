"""Walk the root URLconf and list every URL pattern with its path, name and view."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver


@dataclass(frozen=True)
class RawRoute:
    """A URL pattern as found in the URLconf, before any enrichment."""

    path: str
    name: str | None
    callback: Callable[..., Any]


def walk_urlconf() -> list[RawRoute]:
    """Return every URL pattern reachable from the root resolver, in URLconf order."""
    return list(_walk(get_resolver().url_patterns, prefix="", namespaces=()))


def _walk(
    patterns: Sequence[URLPattern | URLResolver], *, prefix: str, namespaces: tuple[str, ...]
) -> Iterator[RawRoute]:
    for entry in patterns:
        path = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            # include() already falls back to app_name when no namespace is given.
            inner = (*namespaces, entry.namespace) if entry.namespace else namespaces
            yield from _walk(entry.url_patterns, prefix=path, namespaces=inner)
        else:
            name = ":".join((*namespaces, entry.name)) if entry.name else None
            yield RawRoute(path=path, name=name, callback=entry.callback)


def view_identity(callback: Callable[..., Any]) -> str:
    """Dotted path of the view behind `callback`.

    Class-based views resolve to the class through `view_class`. Decorated functions are
    unwrapped through `__wrapped__`; a wrapper without it is recorded under its own name.
    """
    target: Any = getattr(callback, "view_class", None) or callback
    seen: set[int] = set()
    while hasattr(target, "__wrapped__") and id(target) not in seen:
        seen.add(id(target))
        target = target.__wrapped__
    module = getattr(target, "__module__", None) or "<unknown>"
    qualname = getattr(target, "__qualname__", None) or type(target).__qualname__
    return f"{module}.{qualname}"

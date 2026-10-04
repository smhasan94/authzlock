"""Walk the root URLconf and list every URL pattern with its path, name and view."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver

from authzlock.extract.identity import view_class_of, view_identity

__all__ = ["RawRoute", "view_class_of", "view_identity", "walk_urlconf"]


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

"""Derive the HTTP methods a route accepts, and the action map for DRF ViewSets."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

ANY = "any"
_EXCLUDED = frozenset({"HEAD", "OPTIONS"})


def methods_for(callback: Callable[..., Any]) -> tuple[list[str], dict[str, str]]:
    """Return `(methods, actions)` for a URL pattern's callback.

    ViewSet callables from a router carry `actions`; class-based views list the handlers
    they implement that `http_method_names` allows; function views use the
    `require_http_methods` family when present and `["any"]` otherwise.
    """
    action_map: dict[str, str] | None = getattr(callback, "actions", None)
    if action_map:
        actions = {method.upper(): name for method, name in action_map.items()}
        actions = {method: actions[method] for method in _clean(actions)}
        return list(actions), actions

    view_class = getattr(callback, "view_class", None)
    if view_class is not None:
        allowed = getattr(view_class, "http_method_names", ())
        return _clean(m for m in allowed if hasattr(view_class, m)), {}

    restricted = _required_methods(callback)
    return (_clean(restricted) if restricted is not None else [ANY]), {}


def _clean(methods: Iterable[str]) -> list[str]:
    return sorted({m.upper() for m in methods} - _EXCLUDED)


def _required_methods(callback: Callable[..., Any]) -> list[str] | None:
    """The list passed to `require_http_methods`, found in a closure on the wrapper chain."""
    target: Any = callback
    seen: set[int] = set()
    while target is not None and id(target) not in seen:
        seen.add(id(target))
        code = getattr(target, "__code__", None)
        closure = getattr(target, "__closure__", None) or ()
        if code is not None:
            for name, cell in zip(code.co_freevars, closure, strict=False):
                if name == "request_method_list":
                    return list(cell.cell_contents)
        target = getattr(target, "__wrapped__", None)
    return None

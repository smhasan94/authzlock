"""Custom permission classes: a stable string form, and a registry of where each is used.

A class is custom when its module is not `rest_framework.permissions`; third-party classes
count as custom. Classes are only inspected, never instantiated or called. The FastAPI
extractor records dependency callables in the same registry with `Registry.record`.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from typing import Any

BUILTIN_MODULE = "rest_framework.permissions"
_OPERATORS = {"AND": "&", "OR": "|"}


def render_permission(item: Any) -> str:
    """Dotted path of a permission class, or `(left op right)` / `(~operand)` for DRF's
    composed permission holders."""
    if isinstance(item, type):
        return f"{item.__module__}.{item.__qualname__}"
    op1 = getattr(item, "op1_class", None)
    op2 = getattr(item, "op2_class", None)
    operator = getattr(getattr(item, "operator_class", None), "__name__", "")
    if op1 is not None and op2 is not None:
        symbol = _OPERATORS.get(operator, operator)
        return f"({render_permission(op1)} {symbol} {render_permission(op2)})"
    if op1 is not None and operator == "NOT":
        return f"(~{render_permission(op1)})"
    return render_permission(type(item))


def operand_classes(item: Any) -> Iterator[type]:
    """Every class inside a permission entry, left to right."""
    if isinstance(item, type):
        yield item
        return
    for attribute in ("op1_class", "op2_class"):
        operand = getattr(item, attribute, None)
        if operand is not None:
            yield from operand_classes(operand)


def is_custom(klass: type) -> bool:
    return klass.__module__ != BUILTIN_MODULE


def docstring(obj: Any) -> str | None:
    """First paragraph of the docstring of a class, function or method. A class's
    inherited docstring does not count; a callable instance uses its class's."""
    if isinstance(obj, type):
        raw = obj.__dict__.get("__doc__")
    elif inspect.isfunction(obj) or inspect.ismethod(obj):
        raw = obj.__doc__
    else:
        return docstring(type(obj))
    if not isinstance(raw, str) or not raw.strip():
        return None
    first = inspect.cleandoc(raw).split("\n\n", 1)[0]
    return " ".join(first.split())


class Registry:
    """Collects the custom classes, or FastAPI dependency callables, used by each route."""

    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._used_by: dict[str, set[str]] = {}

    def add(self, route_key: str, items: Iterable[Any]) -> None:
        for item in items:
            for klass in operand_classes(item):
                if is_custom(klass):
                    self.record(route_key, render_permission(klass), klass)

    def record(self, route_key: str, path: str, obj: Any) -> None:
        """Record that `route_key` uses `obj`, a class or callable known by `path`."""
        self._objects[path] = obj
        self._used_by.setdefault(path, set()).add(route_key)

    def collect(self) -> dict[str, dict[str, Any]]:
        return {
            path: {
                "name": _name(self._objects[path]),
                "docstring": docstring(self._objects[path]),
                "used_by": sorted(self._used_by[path]),
            }
            for path in sorted(self._objects)
        }


def _name(obj: Any) -> str:
    """`__name__` of a class or function; the class name for a callable instance."""
    name = getattr(obj, "__name__", None)
    return name if isinstance(name, str) else type(obj).__name__

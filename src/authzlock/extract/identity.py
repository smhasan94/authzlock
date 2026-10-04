"""Dotted-path identity of a view; free of Django imports so every extractor can use it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def view_identity(callback: Callable[..., Any]) -> str:
    """Dotted path of the view behind `callback`.

    Class-based views and DRF ViewSets resolve to their class. Decorated functions are
    unwrapped through `__wrapped__`; a wrapper without it is recorded under its own name.
    """
    target: Any = view_class_of(callback) or callback
    seen: set[int] = set()
    while hasattr(target, "__wrapped__") and id(target) not in seen:
        seen.add(id(target))
        target = target.__wrapped__
    module = getattr(target, "__module__", None) or "<unknown>"
    qualname = getattr(target, "__qualname__", None) or type(target).__qualname__
    return f"{module}.{qualname}"


def view_class_of(callback: Callable[..., Any]) -> type | None:
    """The class behind an `as_view()` callable: `view_class` for Django and DRF views,
    `cls` for DRF ViewSets. None for function views."""
    for attribute in ("view_class", "cls"):
        klass = getattr(callback, attribute, None)
        if isinstance(klass, type):
            return klass
    return None

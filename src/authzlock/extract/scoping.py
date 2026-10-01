"""Object-scoping heuristic: does a generic view override its object hooks, and do the
overrides read `request.user`?

This is a heuristic. It cannot prove a filter is correct, it does not follow calls into
helpers, and it never runs the hooks.
"""

from __future__ import annotations

import ast
from typing import Any

from authzlock.extract.source import definition_in, dotted_name, source_of

HOOKS = ("get_object", "get_queryset", "perform_create")
_FRAMEWORK_PACKAGES = ("rest_framework", "django")
_REQUEST_USER = frozenset({"self.request.user", "request.user"})


def resolve(view_class: type | None) -> dict[str, dict[str, bool | None]] | None:
    """One entry per hook for generic class-based views, None for every other view."""
    if view_class is None or not issubclass(view_class, _generic_bases()):
        return None
    result: dict[str, dict[str, bool | None]] = {}
    for hook in HOOKS:
        method = _project_override(view_class, hook)
        if method is None:
            result[hook] = {"overridden": False, "references_request_user": None}
            continue
        source = source_of(method)
        references = references_request_user(source) if source is not None else None
        result[hook] = {"overridden": True, "references_request_user": references}
    return result


def references_request_user(source: str) -> bool:
    """Whether the first definition in `source` reads `self.request.user` or
    `request.user` directly. Calls into helpers are not followed."""
    definition = definition_in(source)
    if definition is None:
        return False
    return any(
        isinstance(node, ast.Attribute) and dotted_name(node) in _REQUEST_USER
        for node in ast.walk(definition)
    )


def _project_override(view_class: type, hook: str) -> Any:
    """The hook as defined by the nearest project class in the MRO, if any. Classes from
    DRF and Django (including DRF's own mixins) do not count as overrides."""
    for klass in view_class.__mro__:
        module = klass.__module__ or ""
        if module.split(".", 1)[0] in _FRAMEWORK_PACKAGES:
            continue
        if hook in klass.__dict__:
            return klass.__dict__[hook]
    return None


def _generic_bases() -> tuple[type, ...]:
    from django.views.generic.detail import SingleObjectMixin
    from django.views.generic.list import MultipleObjectMixin

    bases: tuple[type, ...] = (SingleObjectMixin, MultipleObjectMixin)
    try:
        from rest_framework.generics import GenericAPIView
    except ImportError:
        return bases
    return (*bases, GenericAPIView)

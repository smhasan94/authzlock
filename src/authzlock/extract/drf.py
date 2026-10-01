"""Resolve the effective DRF permission and authentication classes of a view class.

DRF is optional: when it is not installed every lookup returns None. Nothing here
instantiates a view or calls a hook; an overridden `get_permissions` or
`get_authenticators` is recorded as `dynamic`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DYNAMIC = "dynamic"
SOURCE_VIEW = "view"
SOURCE_DEFAULT = "settings-default"
SOURCE_ACTION = "action"


@dataclass(frozen=True)
class DrfInfo:
    permission_classes: tuple[str, ...] | str
    permission_source: str
    authentication_classes: tuple[str, ...] | str
    authentication_source: str


def resolve(view_class: type | None, initkwargs: Mapping[str, Any] | None = None) -> DrfInfo | None:
    """Effective class lists for a DRF view class, or None for anything else.

    `initkwargs` are the keyword arguments the URL pattern passed to `as_view()`. Routers
    pass an `@action`'s own keyword arguments this way, so classes set there win.
    """
    try:
        from rest_framework.settings import api_settings
        from rest_framework.views import APIView
    except ImportError:
        return None
    if not isinstance(view_class, type) or not issubclass(view_class, APIView):
        return None
    own = view_class.__mro__[: view_class.__mro__.index(APIView)]
    permissions, permission_source = _lookup(
        view_class,
        own,
        "permission_classes",
        "get_permissions",
        api_settings.DEFAULT_PERMISSION_CLASSES,
        initkwargs or {},
    )
    authentication, authentication_source = _lookup(
        view_class,
        own,
        "authentication_classes",
        "get_authenticators",
        api_settings.DEFAULT_AUTHENTICATION_CLASSES,
        initkwargs or {},
    )
    return DrfInfo(permissions, permission_source, authentication, authentication_source)


def _lookup(
    view_class: type,
    own: tuple[type, ...],
    attribute: str,
    hook: str,
    default: Any,
    initkwargs: Mapping[str, Any],
) -> tuple[tuple[str, ...] | str, str]:
    # APIView itself copies the settings defaults into its class attributes at import
    # time, so only classes below APIView count as setting the attribute on the view.
    if any(hook in klass.__dict__ for klass in own):
        return DYNAMIC, SOURCE_VIEW
    if attribute in initkwargs:
        return _render_all(initkwargs[attribute]), SOURCE_ACTION
    if any(attribute in klass.__dict__ for klass in own):
        return _render_all(getattr(view_class, attribute)), SOURCE_VIEW
    return _render_all(default), SOURCE_DEFAULT


def _render_all(classes: Any) -> tuple[str, ...]:
    return tuple(sorted(render(item) for item in classes))


def render(item: Any) -> str:
    """Dotted path of a permission class, or a readable form of a composed expression."""
    if isinstance(item, type):
        return class_path(item)
    op1 = getattr(item, "op1_class", None)
    op2 = getattr(item, "op2_class", None)
    operator = getattr(getattr(item, "operator_class", None), "__name__", "")
    if op1 is not None and op2 is not None:
        symbol = {"AND": "&", "OR": "|"}.get(operator, operator)
        return f"({render(op1)} {symbol} {render(op2)})"
    if op1 is not None and operator == "NOT":
        return f"~{render(op1)}"
    return class_path(type(item))


def class_path(klass: type) -> str:
    return f"{klass.__module__}.{klass.__qualname__}"

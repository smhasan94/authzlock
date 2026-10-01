"""Resolve the effective DRF permission and authentication classes of a view class.

DRF is optional: when it is not installed every lookup returns None. Nothing here
instantiates a view or calls a hook; an overridden `get_permissions` or
`get_authenticators` is recorded as `dynamic`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from authzlock.extract.custom import render_permission

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
    # The permission classes and composed holders behind `permission_classes`, for the
    # custom permission registry; empty when the classes are dynamic.
    permission_items: tuple[Any, ...] = ()


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
    return DrfInfo(
        permission_classes=_rendered(permissions),
        permission_source=permission_source,
        authentication_classes=_rendered(authentication),
        authentication_source=authentication_source,
        permission_items=() if permissions == DYNAMIC else tuple(permissions),
    )


def _lookup(
    view_class: type,
    own: tuple[type, ...],
    attribute: str,
    hook: str,
    default: Any,
    initkwargs: Mapping[str, Any],
) -> tuple[Any, str]:
    """The raw class list (or `dynamic`) and where it came from."""
    # APIView itself copies the settings defaults into its class attributes at import
    # time, so only classes below APIView count as setting the attribute on the view.
    if any(hook in klass.__dict__ for klass in own):
        return DYNAMIC, SOURCE_VIEW
    if attribute in initkwargs:
        return tuple(initkwargs[attribute]), SOURCE_ACTION
    if any(attribute in klass.__dict__ for klass in own):
        return tuple(getattr(view_class, attribute)), SOURCE_VIEW
    return tuple(default), SOURCE_DEFAULT


def _rendered(items: Any) -> tuple[str, ...] | str:
    if items == DYNAMIC:
        return DYNAMIC
    return tuple(sorted(render_permission(item) for item in items))

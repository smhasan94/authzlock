"""Build the inventory for the Django project loaded in this process."""

from __future__ import annotations

from authzlock.extract import drf
from authzlock.extract.methods import methods_for
from authzlock.extract.urls import RawRoute, view_class_of, view_identity, walk_urlconf
from authzlock.model import Inventory, Route


def extract() -> Inventory:
    """Return the project's inventory: one route per URL pattern, sorted by path and view."""
    routes = [_route(raw) for raw in walk_urlconf()]
    routes.sort(key=lambda route: (route.path, route.view))
    return Inventory(routes=tuple(routes))


def _route(raw: RawRoute) -> Route:
    methods, actions = methods_for(raw.callback)
    info = drf.resolve(view_class_of(raw.callback))
    return Route(
        path=raw.path,
        name=raw.name,
        view=view_identity(raw.callback),
        methods=tuple(methods),
        actions=actions,
        permission_classes=info.permission_classes if info else None,
        permission_source=info.permission_source if info else None,
        authentication_classes=info.authentication_classes if info else None,
        authentication_source=info.authentication_source if info else None,
    )

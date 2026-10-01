"""Build the inventory for the Django project loaded in this process."""

from __future__ import annotations

from authzlock.extract.methods import methods_for
from authzlock.extract.urls import RawRoute, view_identity, walk_urlconf
from authzlock.model import Inventory, Route


def extract() -> Inventory:
    """Return the project's inventory: one route per URL pattern, sorted by path and view."""
    routes = [_route(raw) for raw in walk_urlconf()]
    routes.sort(key=lambda route: (route.path, route.view))
    return Inventory(routes=tuple(routes))


def _route(raw: RawRoute) -> Route:
    methods, actions = methods_for(raw.callback)
    return Route(
        path=raw.path,
        name=raw.name,
        view=view_identity(raw.callback),
        methods=tuple(methods),
        actions=actions,
    )

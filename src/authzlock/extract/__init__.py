"""Build the inventory for the Django project loaded in this process."""

from __future__ import annotations

from authzlock.extract.urls import view_identity, walk_urlconf
from authzlock.model import Inventory, Route


def extract() -> Inventory:
    """Return the project's inventory: one route per URL pattern, sorted by path and view."""
    routes = [
        Route(path=raw.path, name=raw.name, view=view_identity(raw.callback))
        for raw in walk_urlconf()
    ]
    routes.sort(key=lambda route: (route.path, route.view))
    return Inventory(routes=tuple(routes))

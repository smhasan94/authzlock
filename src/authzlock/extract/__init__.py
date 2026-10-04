"""Build the inventory for the Django project loaded in this process.

Django is imported only when `extract()` runs, so the FastAPI extractor in
`authzlock.extract.fastapi` and the shared helpers here work without Django installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from authzlock.extract import decorators, drf, scoping
from authzlock.extract.custom import Registry
from authzlock.extract.identity import view_class_of, view_identity
from authzlock.extract.methods import methods_for
from authzlock.model import Inventory, Route

if TYPE_CHECKING:
    from authzlock.extract.urls import RawRoute


def extract() -> Inventory:
    """Return the project's inventory: one route per URL pattern, sorted by path and view."""
    from authzlock.extract.urls import walk_urlconf

    registry = Registry()
    routes = []
    for raw in walk_urlconf():
        route, info = _route(raw)
        routes.append(route)
        if info is not None:
            registry.add(route.key(), info.permission_items)
    routes.sort(key=lambda route: (route.path, route.view))
    return Inventory(routes=tuple(routes), custom_permissions=registry.collect())


def _route(raw: RawRoute) -> tuple[Route, drf.DrfInfo | None]:
    methods, actions = methods_for(raw.callback)
    view_class = view_class_of(raw.callback)
    info = drf.resolve(view_class, getattr(raw.callback, "initkwargs", None))
    # DRF views carry their rules in permission classes, not Django auth decorators.
    django_auth = None if info else decorators.resolve(raw.callback, view_class)
    route = Route(
        path=raw.path,
        name=raw.name,
        view=view_identity(raw.callback),
        methods=tuple(methods),
        actions=actions,
        permission_classes=info.permission_classes if info else None,
        permission_source=info.permission_source if info else None,
        authentication_classes=info.authentication_classes if info else None,
        authentication_source=info.authentication_source if info else None,
        django_auth=django_auth.to_dict() if django_auth else None,
        object_scoping=scoping.resolve(view_class),
    )
    return route, info

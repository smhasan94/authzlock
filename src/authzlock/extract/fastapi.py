"""Build the inventory for a FastAPI application without calling any of its code.

Routes come from `app.routes`. Recent FastAPI releases keep an included router behind one
entry and `fastapi.routing.iter_route_contexts` yields its effective routes, with prefixes
and router dependencies applied; older releases copied every route into `app.routes`, so the
list is used as it is when that function does not exist. Mounted applications and routers
are walked with their prefix; a mounted application without routes of its own (static
files, another ASGI app) is one route whose rules are `dynamic`.

Every dependency in a route's dependency tree is recorded by dotted path in
`permission_classes`, with `Security` scopes as `path[scope_a,scope_b]`; security scheme
instances (`fastapi.security.*` and subclasses) are recorded by class path in
`authentication_classes`. Both sources are `dependency`. Dependencies are only inspected,
never called; `app.dependency_overrides` is ignored because it is a test-time setting.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from authzlock.extract.custom import Registry
from authzlock.extract.identity import view_identity
from authzlock.model import Inventory, Route

SOURCE = "dependency"
DYNAMIC = "dynamic"
WEBSOCKET = "WEBSOCKET"
# Dependencies from these packages are FastAPI's own; they are recorded on routes but not
# listed in `custom_permissions`.
FRAMEWORK_PACKAGES = ("fastapi", "starlette")
_FRAMEWORK_PREFIXES = tuple(f"{package}." for package in FRAMEWORK_PACKAGES)
_IGNORED_METHODS = frozenset({"HEAD", "OPTIONS"})


@dataclass(frozen=True)
class _Found:
    """One route as found while walking, with its full path and name."""

    path: str
    name: str | None
    route: Any


def extract_app(app: Any) -> Inventory:
    """Return the inventory of `app`: one route per HTTP or WebSocket route and one per
    mounted application without routes, sorted by path, view and methods."""
    registry = Registry()
    routes = [_route(found, registry) for found in _walk(app.routes, prefix="", names=())]
    routes.sort(key=lambda route: (route.path, route.view, route.methods))
    return Inventory(routes=tuple(routes), custom_permissions=registry.collect())


def _effective(routes: Iterable[Any]) -> list[Any]:
    """`routes` with included routers expanded, on FastAPI releases that defer them."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return list(routes)
    return list(iter_route_contexts(list(routes)))


def _walk(routes: Iterable[Any], *, prefix: str, names: tuple[str, ...]) -> Iterator[_Found]:
    from starlette.routing import Host, Mount

    for route in _effective(routes):
        original = getattr(route, "original_route", route)
        name = getattr(route, "name", None)
        if isinstance(original, (Mount, Host)):
            inner_prefix = prefix + route.path if isinstance(original, Mount) else prefix
            inner_names = (*names, name) if name else names
            inner = getattr(route, "routes", None)
            if inner:
                yield from _walk(inner, prefix=inner_prefix, names=inner_names)
            elif isinstance(original, Mount):
                yield _Found(inner_prefix, ":".join(inner_names) or None, route)
        elif getattr(route, "endpoint", None) is not None:
            full_name = ":".join((*names, name)) if name else None
            yield _Found(prefix + route.path, full_name, route)


def _route(found: _Found, registry: Registry) -> Route:
    from starlette.routing import Mount, WebSocketRoute

    route = found.route
    original = getattr(route, "original_route", route)
    if isinstance(original, Mount):
        return Route(
            path=found.path,
            name=found.name,
            view=view_identity(route.app),
            methods=("any",),
            permission_classes=DYNAMIC,
            permission_source=SOURCE,
            authentication_classes=DYNAMIC,
            authentication_source=SOURCE,
        )
    if isinstance(original, WebSocketRoute):
        methods: tuple[str, ...] = (WEBSOCKET,)
    elif route.methods is None:
        methods = ("any",)
    else:
        methods = tuple(sorted({m.upper() for m in route.methods} - _IGNORED_METHODS))
    permissions, schemes, used = _dependencies(getattr(route, "dependant", None))
    result = Route(
        path=found.path,
        name=found.name,
        view=view_identity(route.endpoint),
        methods=methods,
        permission_classes=permissions,
        permission_source=SOURCE,
        authentication_classes=schemes,
        authentication_source=SOURCE,
    )
    for path, obj in used:
        registry.record(result.key(), path, obj)
    return result


def _dependencies(
    dependant: Any,
) -> tuple[tuple[str, ...], tuple[str, ...], list[tuple[str, Any]]]:
    """Sorted permission entries and scheme classes of a route's dependency tree, and the
    custom callables it uses as (path, object) pairs."""
    from fastapi.security.base import SecurityBase

    permissions: set[str] = set()
    schemes: set[str] = set()
    used: list[tuple[str, Any]] = []
    for dependency in _tree(dependant):
        call = dependency.call
        path, obj = callable_path(call)
        if isinstance(call, SecurityBase):
            schemes.add(path)
        else:
            scopes = _scopes(dependency)
            permissions.add(f"{path}[{','.join(scopes)}]" if scopes else path)
        if not path.startswith(_FRAMEWORK_PREFIXES):
            used.append((path, obj))
    return tuple(sorted(permissions)), tuple(sorted(schemes)), used


def _tree(dependant: Any) -> Iterator[Any]:
    """Every sub-dependency of `dependant`, depth first; the endpoint itself is not one."""
    for dependency in getattr(dependant, "dependencies", None) or ():
        if dependency.call is not None:
            yield dependency
        yield from _tree(dependency)


def _scopes(dependency: Any) -> tuple[str, ...]:
    """Scopes declared by this `Security(...)` itself, sorted and deduplicated.

    Recent FastAPI releases keep them in `own_oauth_scopes`; older releases only have
    `security_scopes`, which also holds the scopes inherited from enclosing dependencies.
    """
    if hasattr(dependency, "own_oauth_scopes"):
        scopes = dependency.own_oauth_scopes
    else:
        scopes = getattr(dependency, "security_scopes", None)
    return tuple(sorted(set(scopes or ())))


def callable_path(call: Any) -> tuple[str, Any]:
    """Dotted path of a dependency callable and the object that documents it.

    Partials are unwrapped to their function and decorated functions through `__wrapped__`;
    a function, class or method is named by its qualified name, any other callable object by
    its class. Lambdas come out as `module.<lambda>`.
    """
    target = call
    while isinstance(target, functools.partial):
        target = target.func
    target = inspect.unwrap(target)
    named = inspect.isfunction(target) or inspect.ismethod(target) or isinstance(target, type)
    owner = target if named else type(target)
    module = getattr(owner, "__module__", None) or "<unknown>"
    return f"{module}.{owner.__qualname__}", target

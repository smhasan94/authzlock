"""Structural diff between two inventories.

`compute(base, current)` is a pure function: it matches routes by `(path, view)`, reports
routes only in `current` as added, routes only in `base` as removed, and every differing
field of a matched route as a `FieldChange`. The nested mappings `django_auth` and
`object_scoping` are flattened to dotted names such as `django_auth.permission_required`
and `object_scoping.get_queryset.overridden`. Custom permission registry differences are
reported in their own lists and never mark a route as changed. Every list is sorted, by
route key for routes and by dotted path for registry entries.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields
from typing import Any

from authzlock.model import Inventory, Route

# Route fields that hold nested mappings and are compared leaf by leaf.
NESTED_FIELDS = ("django_auth", "object_scoping")
# Fields that form the match key; they are equal on both sides of a matched pair.
_MATCH_FIELDS = ("path", "view")
# Registry entry fields, in the order their changes are reported.
_REGISTRY_FIELDS = ("name", "docstring", "used_by")


@dataclass(frozen=True)
class FieldChange:
    """One field whose value differs; `field` is dotted for nested fields."""

    field: str
    old: Any
    new: Any


@dataclass(frozen=True, kw_only=True)
class RouteChange:
    """A route present in both inventories whose recorded fields differ."""

    base: Route
    current: Route
    fields: tuple[FieldChange, ...]

    def key(self) -> str:
        """The current route key; the one output and sorting use."""
        return self.current.key()


@dataclass(frozen=True, kw_only=True)
class CustomPermission:
    """One entry of the custom permission registry, keyed by dotted path."""

    path: str
    name: str | None = None
    docstring: str | None = None
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CustomPermissionChange:
    """A registry entry present in both inventories whose fields differ."""

    path: str
    fields: tuple[FieldChange, ...]


@dataclass(frozen=True, kw_only=True)
class Diff:
    """Everything that differs between a base and a current inventory."""

    added: tuple[Route, ...] = ()
    removed: tuple[Route, ...] = ()
    changed: tuple[RouteChange, ...] = ()
    custom_permissions_added: tuple[CustomPermission, ...] = ()
    custom_permissions_removed: tuple[CustomPermission, ...] = ()
    custom_permissions_changed: tuple[CustomPermissionChange, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.changed
            or self.custom_permissions_added
            or self.custom_permissions_removed
            or self.custom_permissions_changed
        )


def compute(base: Inventory, current: Inventory) -> Diff:
    """Compare two inventories; `base` is the old side, `current` the new one."""
    added: list[Route] = []
    removed: list[Route] = []
    changed: list[RouteChange] = []
    for old, new in _pair_routes(base.routes, current.routes):
        if old is None and new is not None:
            added.append(new)
        elif new is None and old is not None:
            removed.append(old)
        elif old is not None and new is not None:
            route_fields = route_changes(old, new)
            if route_fields:
                changed.append(RouteChange(base=old, current=new, fields=route_fields))

    base_registry = base.custom_permissions
    current_registry = current.custom_permissions
    registry_changed: list[CustomPermissionChange] = []
    for path in sorted(base_registry.keys() & current_registry.keys()):
        entry_fields = _compare(
            (name, base_registry[path].get(name), current_registry[path].get(name))
            for name in _registry_field_names(base_registry[path], current_registry[path])
        )
        if entry_fields:
            registry_changed.append(CustomPermissionChange(path=path, fields=entry_fields))

    return Diff(
        added=tuple(sorted(added, key=Route.key)),
        removed=tuple(sorted(removed, key=Route.key)),
        changed=tuple(sorted(changed, key=RouteChange.key)),
        custom_permissions_added=_registry_entries(current_registry, base_registry),
        custom_permissions_removed=_registry_entries(base_registry, current_registry),
        custom_permissions_changed=tuple(registry_changed),
    )


def route_changes(old: Route, new: Route) -> tuple[FieldChange, ...]:
    """Every differing field of two routes, in lockfile field order, nested ones flattened."""
    triples: list[tuple[str, Any, Any]] = []
    for f in fields(Route):
        if f.name in _MATCH_FIELDS:
            continue
        old_value, new_value = getattr(old, f.name), getattr(new, f.name)
        if f.name in NESTED_FIELDS:
            old_leaves = _flatten(f.name, old_value)
            new_leaves = _flatten(f.name, new_value)
            # A missing mapping or key reads as null, so True -> None is still a change.
            for name in sorted(old_leaves.keys() | new_leaves.keys()):
                triples.append((name, old_leaves.get(name), new_leaves.get(name)))
        else:
            triples.append((f.name, old_value, new_value))
    return _compare(triples)


def _pair_routes(
    base: tuple[Route, ...], current: tuple[Route, ...]
) -> Iterator[tuple[Route | None, Route | None]]:
    """Pair routes by `(path, view)`; unmatched routes pair with None.

    A key that occurs more than once on a side (the same view mounted twice at one path)
    is paired in route key order, and any surplus is reported as added or removed.
    """
    groups: defaultdict[tuple[str, str], tuple[list[Route], list[Route]]] = defaultdict(
        lambda: ([], [])
    )
    for route in base:
        groups[(route.path, route.view)][0].append(route)
    for route in current:
        groups[(route.path, route.view)][1].append(route)
    for olds, news in groups.values():
        olds.sort(key=Route.key)
        news.sort(key=Route.key)
        for index in range(max(len(olds), len(news))):
            yield (
                olds[index] if index < len(olds) else None,
                news[index] if index < len(news) else None,
            )


def _flatten(prefix: str, value: Any) -> dict[str, Any]:
    """Leaves of a nested mapping by dotted name; None flattens to no leaves at all."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        leaves: dict[str, Any] = {}
        for key in value:
            leaves.update(_flatten(f"{prefix}.{key}", value[key]))
        return leaves
    return {prefix: value}


def _freeze(value: Any) -> Any:
    """Lists become tuples so equal values compare equal whatever their source."""
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Mapping):
        return {key: _freeze(value[key]) for key in value}
    return value


def _compare(triples: Iterable[tuple[str, Any, Any]]) -> tuple[FieldChange, ...]:
    changes: list[FieldChange] = []
    for name, old, new in triples:
        old, new = _freeze(old), _freeze(new)
        if old != new:
            changes.append(FieldChange(name, old, new))
    return tuple(changes)


def _registry_field_names(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    extra = sorted((old.keys() | new.keys()) - set(_REGISTRY_FIELDS))
    return [*_REGISTRY_FIELDS, *extra]


def _registry_entries(
    side: Mapping[str, Mapping[str, Any]], other: Mapping[str, Mapping[str, Any]]
) -> tuple[CustomPermission, ...]:
    """Registry entries present in `side` and missing from `other`, sorted by dotted path."""
    return tuple(
        CustomPermission(
            path=path,
            name=side[path].get("name"),
            docstring=side[path].get("docstring"),
            used_by=tuple(side[path].get("used_by") or ()),
        )
        for path in sorted(side.keys() - other.keys())
    )

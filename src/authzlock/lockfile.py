"""Read and write the authzlock lockfile (schema version 1) as YAML.

The serializer chooses every order: top-level keys, route fields, routes by `(path, view)`,
custom permissions by dotted path, and every order-free list. The loader validates the
document and names the offending key path in its errors.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import yaml

from authzlock.errors import LockfileError
from authzlock.model import SCHEMA_VERSION, Inventory

ROUTE_FIELDS = (
    "path",
    "name",
    "view",
    "methods",
    "actions",
    "permission_classes",
    "permission_source",
    "authentication_classes",
    "authentication_source",
    "django_auth",
    "object_scoping",
)
TOP_LEVEL = ("schema_version", "routes", "custom_permissions")
_DYNAMIC = "dynamic"
# Lists whose order carries no meaning; they are sorted wherever they appear.
_ORDER_FREE = frozenset(
    {
        "methods",
        "permission_classes",
        "authentication_classes",
        "permission_required",
        "unknown_decorators",
        "used_by",
    }
)


class _Dumper(yaml.SafeDumper):
    """Never emits anchors or aliases, even for repeated objects."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def dump(inventory: Inventory) -> str:
    """The lockfile text for `inventory`."""
    data = inventory.to_dict()
    routes = sorted(data["routes"], key=lambda route: (route["path"], route["view"]))
    document = {
        "schema_version": data["schema_version"],
        "routes": [{key: _normalise(key, route[key]) for key in ROUTE_FIELDS} for route in routes],
        "custom_permissions": {
            name: _normalise(name, data["custom_permissions"][name])
            for name in sorted(data["custom_permissions"])
        },
    }
    return yaml.dump(
        document,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
        line_break="\n",
    )


def _normalise(key: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _normalise(k, value[k]) for k in sorted(value)}
    if isinstance(value, list):
        items = [_normalise(key, item) for item in value]
        return sorted(items) if key in _ORDER_FREE else items
    return value


def load(text: str) -> Inventory:
    """Parse and validate lockfile text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LockfileError(f"the lockfile is not valid YAML: {exc}") from exc
    _validate(data)
    return Inventory.from_dict(data)


def _validate(data: Any) -> None:
    if not isinstance(data, dict):
        raise LockfileError("the lockfile must be a mapping with schema_version and routes")
    version = data.get("schema_version")
    if version is None:
        raise LockfileError("missing required key: schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise LockfileError(f"schema_version: unknown value {version!r}; expected {SCHEMA_VERSION}")
    if version > SCHEMA_VERSION:
        raise LockfileError(
            f"schema_version {version} is newer than the supported version {SCHEMA_VERSION}; "
            "upgrade authzlock to read this lockfile"
        )
    for key in data:
        if key not in TOP_LEVEL:
            raise LockfileError(f"unknown top-level key: {key}")
    if "routes" not in data:
        raise LockfileError("missing required key: routes")
    routes = data["routes"]
    if not isinstance(routes, list):
        raise LockfileError("routes: expected a list")
    for index, route in enumerate(routes):
        _validate_route(route, f"routes[{index}]")
    permissions = data.get("custom_permissions", {})
    if not isinstance(permissions, dict):
        raise LockfileError("custom_permissions: expected a mapping")
    for name, entry in permissions.items():
        if not isinstance(entry, dict):
            raise LockfileError(f"custom_permissions.{name}: expected a mapping")


def _validate_route(route: Any, where: str) -> None:
    if not isinstance(route, dict):
        raise LockfileError(f"{where}: expected a mapping")
    for key in ROUTE_FIELDS:
        if key not in route:
            raise LockfileError(f"{where}: missing required key {key}")
    for key in route:
        if key not in ROUTE_FIELDS:
            raise LockfileError(f"{where}: unknown key {key}")
    for key, (check, expected) in _ROUTE_CHECKS.items():
        if not check(route[key]):
            raise LockfileError(f"{where}.{key}: expected {expected}, got {route[key]!r}")


def _str(value: Any) -> bool:
    return isinstance(value, str)


def _optional_str(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _str_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(item, str) for item in (*value, *value.values())
    )


def _class_list(value: Any) -> bool:
    return value is None or value == _DYNAMIC or _str_list(value)


def _optional_map(value: Any) -> bool:
    return value is None or isinstance(value, dict)


_ROUTE_CHECKS: dict[str, tuple[Callable[[Any], bool], str]] = {
    "path": (_str, "a string"),
    "name": (_optional_str, "a string or null"),
    "view": (_str, "a string"),
    "methods": (_str_list, "a list of strings"),
    "actions": (_str_map, "a mapping of strings"),
    "permission_classes": (_class_list, 'a list of strings, "dynamic" or null'),
    "permission_source": (_optional_str, "a string or null"),
    "authentication_classes": (_class_list, 'a list of strings, "dynamic" or null'),
    "authentication_source": (_optional_str, "a string or null"),
    "django_auth": (_optional_map, "a mapping or null"),
    "object_scoping": (_optional_map, "a mapping or null"),
}

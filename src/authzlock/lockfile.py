"""Read and write the authzlock lockfile (schema version 1) as YAML.

The serializer chooses every order: top-level keys, route fields, routes by `(path, view)`,
custom permissions by dotted path, and every order-free list. It refuses to write a value
that looks like an absolute file path, so nothing specific to one machine reaches the file.
The loader validates the document and names the offending key path in its errors.
"""

from __future__ import annotations

import re
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
TOP_LEVEL = ("schema_version", "ignore", "routes", "custom_permissions")
IGNORE_KEYS = ("paths", "views")
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
# A POSIX root, a Windows drive letter or a UNC share at the start of a value.
_ABSOLUTE_PATH = re.compile(r"/|[A-Za-z]:[\\/]|\\\\")
# Keys whose values are not dotted paths: a URL pattern may start with "/", and a docstring
# is the project's own text, the same on every machine.
_FREE_TEXT = frozenset({"path", "docstring"})


class _Dumper(yaml.SafeDumper):
    """Never emits anchors or aliases, even for repeated objects."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def dump(inventory: Inventory) -> str:
    """The lockfile text for `inventory`."""
    data = inventory.to_dict()
    _reject_absolute_paths(data)
    routes = sorted(data["routes"], key=lambda route: (route["path"], route["view"]))
    document: dict[str, Any] = {"schema_version": data["schema_version"]}
    if "ignore" in data:
        document["ignore"] = {key: sorted(set(data["ignore"][key])) for key in data["ignore"]}
    document |= {
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


def _reject_absolute_paths(data: Mapping[str, Any]) -> None:
    """Raise `LockfileError` if a value would tie the lockfile to one checkout location."""
    for index, route in enumerate(data["routes"]):
        for key in ROUTE_FIELDS:
            _check_value(route.get(key), f"routes[{index}].{key}", key)
    for name, entry in data["custom_permissions"].items():
        _check_value(name, f"custom_permissions.{name}", "")
        _check_value(entry, f"custom_permissions.{name}", "")
    # Ignored paths are URL prefixes, free text like a route path; view prefixes are dotted.
    _check_value(data.get("ignore", {}).get("views"), "ignore.views", "views")


def _check_value(value: Any, where: str, key: str) -> None:
    if key in _FREE_TEXT:
        return
    if isinstance(value, str):
        if _ABSOLUTE_PATH.match(value):
            raise LockfileError(
                f"{where}: refusing to write the absolute path {value!r}; the lockfile must "
                "not depend on where the project is checked out"
            )
    elif isinstance(value, Mapping):
        for item_key, item in value.items():
            _check_value(item_key, f"{where}.{item_key}", "")
            _check_value(item, f"{where}.{item_key}", str(item_key))
    elif isinstance(value, list | tuple):
        for position, item in enumerate(value):
            _check_value(item, f"{where}[{position}]", key)


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
    if "ignore" in data:
        _validate_ignore(data["ignore"])
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


def _validate_ignore(ignore: Any) -> None:
    if not isinstance(ignore, dict):
        raise LockfileError("ignore: expected a mapping with paths and/or views")
    for key, value in ignore.items():
        if key not in IGNORE_KEYS:
            raise LockfileError(f"ignore: unknown key {key}")
        if not isinstance(value, list):
            raise LockfileError(f"ignore.{key}: expected a list of strings, got {value!r}")
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item:
                raise LockfileError(
                    f"ignore.{key}[{index}]: expected a non-empty string, got {item!r}"
                )


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

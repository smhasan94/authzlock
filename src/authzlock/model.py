"""The inventory of routes and their access rules that extraction produces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import Any

SCHEMA_VERSION = 1

# A class list is a tuple of dotted paths, the string "dynamic" when the tool must not
# guess, or None when the field does not apply.
ClassList = tuple[str, ...] | str | None


def _class_list(value: Any) -> ClassList:
    if value is None or isinstance(value, str):
        return value
    return tuple(value)


def _plain(value: Any) -> Any:
    """Convert tuples to lists so a dict is ready for JSON or YAML."""
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    return value


@dataclass(frozen=True, kw_only=True)
class Route:
    """One URL pattern and what guards it. Field order is the lockfile order."""

    path: str
    name: str | None
    view: str
    methods: tuple[str, ...] = ()
    actions: Mapping[str, str] = field(default_factory=dict)
    permission_classes: ClassList = None
    permission_source: str | None = None
    authentication_classes: ClassList = None
    authentication_source: str | None = None
    django_auth: Mapping[str, Any] | None = None
    object_scoping: Mapping[str, Any] | None = None

    def key(self) -> str:
        """The route key used in `used_by`, diffs and output."""
        target = f"{self.path} -> {self.view}"
        return f"{','.join(self.methods)} {target}" if self.methods else target

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _plain(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Route:
        return cls(
            path=data["path"],
            name=data.get("name"),
            view=data["view"],
            methods=tuple(data.get("methods") or ()),
            actions=dict(data.get("actions") or {}),
            permission_classes=_class_list(data.get("permission_classes")),
            permission_source=data.get("permission_source"),
            authentication_classes=_class_list(data.get("authentication_classes")),
            authentication_source=data.get("authentication_source"),
            django_auth=data.get("django_auth"),
            object_scoping=data.get("object_scoping"),
        )


@dataclass(frozen=True)
class IgnoreList:
    """Path prefixes and view module prefixes left out of the lockfile; see `ignore.py`."""

    paths: tuple[str, ...] = ()
    views: tuple[str, ...] = ()

    @classmethod
    def of(cls, paths: Sequence[str] = (), views: Sequence[str] = ()) -> IgnoreList:
        """A list with `paths` and `views` sorted and deduplicated."""
        return cls(tuple(sorted(set(paths))), tuple(sorted(set(views))))

    @property
    def is_empty(self) -> bool:
        return not self.paths and not self.views

    def to_dict(self) -> dict[str, list[str]]:
        """Only the non-empty lists, `paths` first."""
        data = {"paths": list(self.paths), "views": list(self.views)}
        return {key: value for key, value in data.items() if value}


@dataclass(frozen=True)
class Inventory:
    """Everything extraction found in one project.

    `ignore` is the list `update` recorded; extraction itself never sets it.
    """

    schema_version: int = SCHEMA_VERSION
    routes: tuple[Route, ...] = ()
    custom_permissions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    ignore: IgnoreList = field(default_factory=IgnoreList)

    def to_dict(self) -> dict[str, Any]:
        """The lockfile document; `ignore` is present only when the list is not empty."""
        ignore = {} if self.ignore.is_empty else {"ignore": self.ignore.to_dict()}
        return {
            "schema_version": self.schema_version,
            **ignore,
            "routes": [route.to_dict() for route in self.routes],
            "custom_permissions": {
                name: dict(self.custom_permissions[name])
                for name in sorted(self.custom_permissions)
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inventory:
        routes: Sequence[Mapping[str, Any]] = data.get("routes", ())
        ignore: Mapping[str, Sequence[str]] = data.get("ignore") or {}
        return cls(
            schema_version=int(data["schema_version"]),
            routes=tuple(Route.from_dict(route) for route in routes),
            custom_permissions=dict(data.get("custom_permissions", {})),
            ignore=IgnoreList.of(ignore.get("paths", ()), ignore.get("views", ())),
        )

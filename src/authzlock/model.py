"""The inventory of routes and their access rules that extraction produces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Inventory:
    """Everything extraction found in one project. Routes are added by later tickets."""

    schema_version: int = SCHEMA_VERSION
    routes: tuple[Mapping[str, Any], ...] = ()
    custom_permissions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "routes": [dict(route) for route in self.routes],
            "custom_permissions": {
                name: dict(self.custom_permissions[name])
                for name in sorted(self.custom_permissions)
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inventory:
        return cls(
            schema_version=int(data["schema_version"]),
            routes=tuple(data.get("routes", ())),
            custom_permissions=dict(data.get("custom_permissions", {})),
        )

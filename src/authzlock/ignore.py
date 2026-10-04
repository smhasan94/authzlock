"""Leave routes out of the lockfile by path prefix or view module prefix.

`update` records the list in the lockfile under `ignore`; `check` and `diff` apply the
recorded list to a fresh extraction, so every command filters the same routes. Filtering
happens after extraction: `extract()` and `_dump` always see every route.

A path prefix is compared literally with the route's URL pattern after one leading `^` is
stripped from each, so `admin/` also covers `re_path(r"^admin/...")`. A view prefix
matches the view's dotted path on a module boundary: `shop.internal` matches
`shop.internal` and `shop.internal.views.X`, never `shop.internal_api.views.X`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from authzlock.model import IgnoreList, Inventory, Route

__all__ = ["IgnoreList", "apply", "matches"]


def _unanchored(pattern: str) -> str:
    return pattern[1:] if pattern.startswith("^") else pattern


def matches(route: Route, ignore: IgnoreList) -> bool:
    """True if `ignore` leaves `route` out."""
    path = _unanchored(route.path)
    if any(path.startswith(_unanchored(prefix)) for prefix in ignore.paths):
        return True
    return any(
        route.view == prefix or route.view.startswith(f"{prefix}.") for prefix in ignore.views
    )


def apply(inventory: Inventory, ignore: IgnoreList) -> Inventory:
    """`inventory` without the routes `ignore` matches, recording `ignore` on the result.

    Dropped route keys leave every custom permission's `used_by`; a custom permission that
    only dropped routes used is removed.
    """
    dropped = {route.key() for route in inventory.routes if matches(route, ignore)}
    routes = tuple(route for route in inventory.routes if route.key() not in dropped)
    permissions: dict[str, Any] = {}
    for name, entry in inventory.custom_permissions.items():
        used_by = list(entry.get("used_by") or ())
        remaining = [key for key in used_by if key not in dropped]
        if used_by and not remaining:
            continue
        permissions[name] = {**entry, "used_by": remaining} if "used_by" in entry else entry
    return replace(inventory, routes=routes, custom_permissions=permissions, ignore=ignore)

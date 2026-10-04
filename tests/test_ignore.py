"""Unit tests for SHA-245: matching, applying and storing the route ignore list."""

from __future__ import annotations

import pytest

from authzlock import lockfile
from authzlock.errors import LockfileError
from authzlock.ignore import apply, matches
from authzlock.model import IgnoreList, Inventory, Route


def _route(path: str, view: str, methods: tuple[str, ...] = ("GET",)) -> Route:
    return Route(path=path, name=None, view=view, methods=methods)


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("admin/", "admin/", True),
        ("admin/auth/user/", "admin/", True),
        ("^admin/(?P<x>.+)$", "admin/", True),
        ("admin/", "^admin/", True),
        ("^admin/$", "^admin/", True),
        ("administrators/", "admin/", False),
        ("api/admin/", "admin/", False),
        ("", "admin/", False),
    ],
)
def test_t8_matches_strips_caret_on_either_side(path: str, prefix: str, expected: bool) -> None:
    assert matches(_route(path, "shop.views.x"), IgnoreList.of(paths=[prefix])) is expected


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        ("shop.internal", True),
        ("shop.internal.views.StockView", True),
        ("shop.internal_api.views.status", False),
        ("shop.internals.views.x", False),
        ("other.shop.internal.views.x", False),
    ],
)
def test_t8_matches_view_prefix_only_on_module_boundary(view: str, expected: bool) -> None:
    assert matches(_route("x/", view), IgnoreList.of(views=["shop.internal"])) is expected


def test_t7_apply_trims_used_by_and_drops_unused_custom_permission() -> None:
    internal = _route("internal/stock/", "shop.internal.views.StockView")
    public = _route("products/", "shop.views.products")
    inventory = Inventory(
        routes=(internal, public),
        custom_permissions={
            "shop.permissions.Shared": {
                "name": "Shared",
                "docstring": None,
                "used_by": [internal.key(), public.key()],
            },
            "shop.permissions.InternalOnly": {
                "name": "InternalOnly",
                "docstring": None,
                "used_by": [internal.key()],
            },
        },
    )
    ignore = IgnoreList.of(views=["shop.internal"])

    result = apply(inventory, ignore)

    assert result.routes == (public,)
    assert result.ignore == ignore
    assert set(result.custom_permissions) == {"shop.permissions.Shared"}
    assert result.custom_permissions["shop.permissions.Shared"]["used_by"] == [public.key()]
    # The input is not modified.
    assert len(inventory.custom_permissions["shop.permissions.Shared"]["used_by"]) == 2


def test_extra_apply_with_empty_list_keeps_everything() -> None:
    route = _route("admin/", "django.contrib.admin.sites.index")
    inventory = Inventory(routes=(route,))

    assert apply(inventory, IgnoreList()) == inventory


def test_t9_loader_rejects_non_string_ignore_entries_naming_path() -> None:
    text = "schema_version: 1\nignore:\n  paths:\n  - 3\nroutes: []\n"

    with pytest.raises(LockfileError, match=r"ignore\.paths\[0\]"):
        lockfile.load(text)


@pytest.mark.parametrize(
    ("ignore", "message"),
    [
        ("[admin/]", "expected a mapping"),
        ("{globs: [x]}", "unknown key globs"),
        ("{views: shop.internal}", r"ignore\.views: expected a list"),
        ("{views: ['']}", r"ignore\.views\[0\]"),
    ],
)
def test_extra_loader_rejects_malformed_ignore(ignore: str, message: str) -> None:
    with pytest.raises(LockfileError, match=message):
        lockfile.load(f"schema_version: 1\nignore: {ignore}\nroutes: []\n")


def test_t3_lists_are_sorted_deduplicated_and_absent_when_empty() -> None:
    route = _route("products/", "shop.views.products")
    plain = lockfile.dump(Inventory(routes=(route,)))
    ignored = lockfile.dump(
        Inventory(routes=(route,), ignore=IgnoreList.of(["b/", "a/", "b/"], ["z.y", "x"]))
    )

    assert "ignore" not in plain
    assert ignored.startswith(
        "schema_version: 1\nignore:\n  paths:\n  - a/\n  - b/\n  views:\n  - x\n  - z.y\nroutes:\n"
    )
    assert ignored.split("routes:\n", 1)[1] == plain.split("routes:\n", 1)[1]
    assert lockfile.load(ignored).ignore == IgnoreList(("a/", "b/"), ("x", "z.y"))
    assert lockfile.load(plain).ignore == IgnoreList()


def test_extra_only_non_empty_lists_are_written() -> None:
    text = lockfile.dump(Inventory(ignore=IgnoreList.of(views=["shop.internal"])))

    assert "ignore:\n  views:\n  - shop.internal\n" in text
    assert "paths" not in text


def test_extra_absolute_view_prefix_is_refused() -> None:
    with pytest.raises(LockfileError, match="ignore.views"):
        lockfile.dump(Inventory(ignore=IgnoreList.of(views=["/srv/app"])))

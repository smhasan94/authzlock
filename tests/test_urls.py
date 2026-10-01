"""Tests for SHA-200: URL resolver walk and route model."""

from __future__ import annotations

from typing import Any

import pytest

from authzlock.extract.urls import view_identity
from harness import run_extract

SHOP_ROUTES = [
    ("", "list", "shop.views.product_list"),
    ("<int:pk>/", "detail", "shop.views.ProductDetail"),
    ("export/", None, "shop.views.export"),
    ("^legacy/(?P<sku>[0-9]+)/$", "legacy", "shop.views.legacy_product"),
]

EXPECTED_PATHS = {
    "public/",
    "members/",
    "reports/staff/",
    "audited/",
    "orders/",
    "status/",
    "^archive/(?P<year>[0-9]{4})/$",
    *(f"{prefix}{path}" for prefix in ("shop/", "a/", "b/") for path, _, _ in SHOP_ROUTES),
}


@pytest.fixture(scope="module")
def routes() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = run_extract("function_views")["routes"]
    return data


def _by_path(routes: list[dict[str, Any]], path: str) -> dict[str, Any]:
    matches = [route for route in routes if route["path"] == path]
    assert len(matches) == 1, f"{path!r} appears {len(matches)} times"
    return matches[0]


def test_t1_every_pattern_appears_once_with_joined_path(routes: list[dict[str, Any]]) -> None:
    paths = [route["path"] for route in routes]
    assert len(paths) == len(set(paths))
    assert set(paths) == EXPECTED_PATHS


def test_t2_namespaced_route_name(routes: list[dict[str, Any]]) -> None:
    assert _by_path(routes, "shop/")["name"] == "shop:list"
    assert _by_path(routes, "a/<int:pk>/")["name"] == "a:detail"


def test_t3_unnamed_route_has_null_name(routes: list[dict[str, Any]]) -> None:
    assert _by_path(routes, "shop/export/")["name"] is None


def test_t4_view_identity_for_function_and_class_views(routes: list[dict[str, Any]]) -> None:
    assert _by_path(routes, "public/")["view"] == "shop.views.public"
    assert _by_path(routes, "members/")["view"] == "shop.views.members_only"
    assert _by_path(routes, "shop/<int:pk>/")["view"] == "shop.views.ProductDetail"


def test_t5_re_path_keeps_regex_source(routes: list[dict[str, Any]]) -> None:
    route = _by_path(routes, "^archive/(?P<year>[0-9]{4})/$")
    assert route["view"] == "shop.views.archive"
    nested = _by_path(routes, "shop/^legacy/(?P<sku>[0-9]+)/$")
    assert nested["name"] == "shop:legacy"


def test_t6_same_include_twice_yields_two_routes(routes: list[dict[str, Any]]) -> None:
    mirrored = [_by_path(routes, prefix + "export/") for prefix in ("a/", "b/")]
    assert [route["view"] for route in mirrored] == ["shop.views.export"] * 2


def test_t7_wrapper_without_wraps_is_recorded_not_crashed(
    routes: list[dict[str, Any]],
) -> None:
    def plain(view: Any) -> Any:
        def wrapper(request: Any) -> Any:
            return view(request)

        return wrapper

    @plain
    def index(request: Any) -> Any:
        return None

    assert view_identity(index) == f"{__name__}.{plain.__qualname__}.<locals>.wrapper"
    assert _by_path(routes, "audited/")["view"] == "shop.views.audit.<locals>.inner"


def test_extra_routes_are_sorted_by_path_then_view(routes: list[dict[str, Any]]) -> None:
    keys = [(route["path"], route["view"]) for route in routes]
    assert keys == sorted(keys)


def test_extra_routes_carry_every_lockfile_field(routes: list[dict[str, Any]]) -> None:
    assert set(_by_path(routes, "public/")) == {
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
    }

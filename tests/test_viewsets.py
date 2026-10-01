"""Tests for SHA-207: ViewSets, routers, nested routers and @action routes."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from harness import run_extract

INVOICES = "billing.views.InvoiceViewSet"
LIST = "^invoices/$"
DETAIL = "^invoices/(?P<pk>[^/.]+)/$"


@pytest.fixture(scope="module")
def routes() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = run_extract("drf_viewsets")["routes"]
    return data


def _by_path(routes: list[dict[str, Any]], path: str) -> dict[str, Any]:
    matches = [route for route in routes if route["path"] == path]
    assert len(matches) == 1, f"{path!r} appears {len(matches)} times"
    return matches[0]


def test_t1_modelviewset_list_and_detail_routes(routes: list[dict[str, Any]]) -> None:
    listing = _by_path(routes, LIST)
    detail = _by_path(routes, DETAIL)
    assert listing["methods"] == ["GET", "POST"]
    assert detail["methods"] == ["DELETE", "GET", "PATCH", "PUT"]
    assert listing["view"] == detail["view"] == INVOICES
    assert detail["actions"]["DELETE"] == "destroy"


def test_t2_action_with_own_permission_classes(routes: list[dict[str, Any]]) -> None:
    route = _by_path(routes, "^invoices/(?P<pk>[^/.]+)/archive/$")
    assert route["methods"] == ["POST"]
    assert route["actions"] == {"POST": "archive"}
    assert route["permission_classes"] == ["rest_framework.permissions.IsAdminUser"]
    assert route["permission_source"] == "action"
    assert route["authentication_source"] == "settings-default"


def test_t3_action_without_classes_inherits_viewset(routes: list[dict[str, Any]]) -> None:
    route = _by_path(routes, "^invoices/summary/$")
    listing = _by_path(routes, LIST)
    assert route["actions"] == {"GET": "summary"}
    assert route["permission_classes"] == listing["permission_classes"]
    assert route["permission_source"] == listing["permission_source"] == "view"


def test_t4_nested_router_route(routes: list[dict[str, Any]]) -> None:
    nested = [
        route
        for route in routes
        if route["path"].startswith("^invoices/(?P<invoice_pk>") and "/lines/" in route["path"]
    ]
    assert nested
    assert {route["view"] for route in nested} == {"billing.views.LineViewSet"}


def test_t5_readonly_viewset_has_no_write_methods(routes: list[dict[str, Any]]) -> None:
    customers = [route for route in routes if route["view"] == "billing.views.CustomerViewSet"]
    assert customers
    for route in customers:
        assert route["methods"] == ["GET"]


def test_t6_api_root_is_recorded(routes: list[dict[str, Any]]) -> None:
    roots = [route for route in routes if route["view"].endswith("APIRootView")]
    assert roots
    assert all(route["methods"] == ["GET"] for route in roots)


def test_t7_same_viewset_on_two_routers_no_duplicates(routes: list[dict[str, Any]]) -> None:
    v1 = [r for r in routes if r["view"] == INVOICES and not r["path"].startswith("v2/")]
    v2 = [r for r in routes if r["view"] == INVOICES and r["path"].startswith("v2/")]
    assert {LIST, DETAIL} <= {r["path"] for r in v1}
    assert {"v2/" + LIST, "v2/" + DETAIL} <= {r["path"] for r in v2}
    for group in (v1, v2):
        counts = Counter(r["path"] for r in group)
        assert max(counts.values()) == 1

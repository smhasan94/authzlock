"""Tests for SHA-205: DRF permission and authentication resolution."""

from __future__ import annotations

from typing import Any

import pytest

from harness import run_extract

IS_AUTHENTICATED = "rest_framework.permissions.IsAuthenticated"
SESSION_AUTH = ["rest_framework.authentication.SessionAuthentication"]


@pytest.fixture(scope="module")
def routes() -> dict[str, dict[str, Any]]:
    return {route["path"]: route for route in run_extract("drf_apiview")["routes"]}


def test_t1_explicit_permission_classes_source_view(routes: dict[str, dict[str, Any]]) -> None:
    route = routes["explicit/"]
    assert route["permission_classes"] == [IS_AUTHENTICATED]
    assert route["permission_source"] == "view"


def test_t2_settings_default_is_used_with_source(routes: dict[str, dict[str, Any]]) -> None:
    route = routes["orders/"]
    assert route["permission_classes"] == ["rest_framework.permissions.IsAuthenticatedOrReadOnly"]
    assert route["permission_source"] == "settings-default"


def test_t3_get_permissions_override_is_dynamic_and_never_called(
    routes: dict[str, dict[str, Any]],
) -> None:
    route = routes["dynamic/"]
    assert route["permission_classes"] == "dynamic"
    assert route["permission_source"] == "view"


def test_t4_base_class_attribute_is_inherited(routes: dict[str, dict[str, Any]]) -> None:
    route = routes["staff/report/"]
    assert route["permission_classes"] == ["rest_framework.permissions.IsAdminUser"]
    assert route["permission_source"] == "view"
    assert routes["orders/<int:pk>/"]["permission_classes"] == ["api.permissions.IsOwner"]


def test_t5_authentication_defaults(routes: dict[str, dict[str, Any]]) -> None:
    route = routes["explicit/"]
    assert route["authentication_classes"] == SESSION_AUTH
    assert route["authentication_source"] == "settings-default"


def test_t6_plain_django_view_has_null_fields(routes: dict[str, dict[str, Any]]) -> None:
    route = routes["health/"]
    for field in (
        "permission_classes",
        "permission_source",
        "authentication_classes",
        "authentication_source",
    ):
        assert route[field] is None


def test_t7_extraction_without_drf() -> None:
    routes = run_extract("function_views", block_modules=("rest_framework",))["routes"]
    assert routes
    for route in routes:
        assert route["permission_classes"] is None
        assert route["authentication_classes"] is None


def test_t8_get_authenticators_override_only_affects_authentication(
    routes: dict[str, dict[str, Any]],
) -> None:
    route = routes["token/"]
    assert route["authentication_classes"] == "dynamic"
    assert route["authentication_source"] == "view"
    assert route["permission_classes"] == [IS_AUTHENTICATED]
    assert route["permission_source"] == "view"

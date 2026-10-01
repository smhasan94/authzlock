"""Tests for SHA-209: Django auth decorators and mixins."""

from __future__ import annotations

from typing import Any

import pytest

from authzlock.extract.decorators import from_source, resolve
from harness import run_extract

NONE = {
    "login_required": False,
    "permission_required": [],
    "user_passes_test": False,
    "unknown_decorators": [],
}


def _routes(fixture: str) -> dict[str, dict[str, Any]]:
    return {route["path"]: route for route in run_extract(fixture)["routes"]}


@pytest.fixture(scope="module")
def function_views() -> dict[str, dict[str, Any]]:
    return _routes("function_views")


@pytest.fixture(scope="module")
def class_views() -> dict[str, dict[str, Any]]:
    return _routes("class_views")


def test_t1_login_required_function_view(function_views: dict[str, dict[str, Any]]) -> None:
    auth = function_views["members/"]["django_auth"]
    assert auth == {**NONE, "login_required": True}
    assert function_views["public/"]["django_auth"] == NONE


def test_t2_permission_required_string_and_list_forms(
    function_views: dict[str, dict[str, Any]],
) -> None:
    assert function_views["orders/delete/"]["django_auth"]["permission_required"] == [
        "shop.delete_order"
    ]
    assert function_views["orders/bulk/"]["django_auth"]["permission_required"] == [
        "shop.add_order",
        "shop.change_order",
    ]


def test_t3_user_passes_test_flag_without_calling(
    function_views: dict[str, dict[str, Any]],
) -> None:
    auth = function_views["staff/tools/"]["django_auth"]
    assert auth == {**NONE, "user_passes_test": True}


def test_t4_mixin_and_method_decorator_on_class_views(
    class_views: dict[str, dict[str, Any]],
) -> None:
    assert class_views["account/"]["django_auth"] == {**NONE, "login_required": True}
    assert class_views["settings/"]["django_auth"] == {**NONE, "login_required": True}
    assert class_views["items/"]["django_auth"] == NONE


def test_t5_permission_required_mixin_attribute(class_views: dict[str, dict[str, Any]]) -> None:
    assert class_views["orders/"]["django_auth"] == {
        **NONE,
        "permission_required": ["shop.view_order"],
    }
    assert class_views["staff/"]["django_auth"] == {**NONE, "user_passes_test": True}


def test_t6_unknown_decorator_is_listed(function_views: dict[str, dict[str, Any]]) -> None:
    assert function_views["cached/"]["django_auth"] == {
        **NONE,
        "unknown_decorators": ["cache_page"],
    }
    assert function_views["orders/"]["django_auth"] == NONE


def test_t7_unreadable_source_falls_back_to_runtime() -> None:
    namespace: dict[str, Any] = {}
    exec(
        "from django.contrib.auth.decorators import login_required\n"
        "@login_required\n"
        "def view(request):\n"
        "    return None\n",
        namespace,
    )
    assert resolve(namespace["view"], None).to_dict() == {**NONE, "login_required": True}

    exec("def plain(request):\n    return None\n", namespace)
    assert resolve(namespace["plain"], None).to_dict() == NONE


def test_t8_non_literal_permission_argument_is_not_guessed() -> None:
    source = (
        "@permission_required(PERM_CONSTANT)\n"
        "@permission_required('shop.view_order')\n"
        "def view(request):\n"
        "    return None\n"
    )
    auth = from_source(source)
    assert auth.permission_required == ("shop.view_order",)
    assert auth.unknown_decorators == ("permission_required(<non-literal>)",)


def test_extra_runtime_reads_constant_permission(
    function_views: dict[str, dict[str, Any]],
) -> None:
    auth = function_views["orders/export/"]["django_auth"]
    assert auth == {**NONE, "permission_required": ["shop.export_order"]}


def test_extra_method_restricting_decorators_are_known(
    function_views: dict[str, dict[str, Any]],
) -> None:
    assert function_views["status/"]["django_auth"]["unknown_decorators"] == ["logged"]


def test_extra_drf_views_have_no_django_auth() -> None:
    routes = _routes("drf_apiview")
    assert routes["explicit/"]["django_auth"] is None
    assert routes["dynamic/"]["django_auth"] is None
    assert routes["health/"]["django_auth"] == NONE

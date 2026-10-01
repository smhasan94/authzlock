"""Tests for SHA-203: HTTP methods and ViewSet actions."""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from typing import Any

import pytest
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from authzlock.extract.methods import methods_for
from harness import FIXTURES, fixture_env, run_extract


def _routes(fixture: str) -> dict[str, dict[str, Any]]:
    return {route["path"]: route for route in run_extract(fixture)["routes"]}


@pytest.fixture(scope="module")
def class_views() -> dict[str, dict[str, Any]]:
    return _routes("class_views")


@pytest.fixture(scope="module")
def function_views() -> dict[str, dict[str, Any]]:
    return _routes("function_views")


def test_t1_class_view_lists_implemented_handlers(class_views: dict[str, dict[str, Any]]) -> None:
    assert class_views["items/"]["methods"] == ["GET", "POST"]
    assert class_views["about/"]["methods"] == ["GET"]
    assert class_views["old/"]["methods"] == ["DELETE", "GET", "PATCH", "POST", "PUT"]
    assert class_views["items/"]["actions"] == {}


def test_t2_require_http_methods_is_read(function_views: dict[str, dict[str, Any]]) -> None:
    assert function_views["orders/"]["methods"] == ["POST", "PUT"]


def test_t3_plain_function_view_is_any(function_views: dict[str, dict[str, Any]]) -> None:
    assert function_views["public/"]["methods"] == ["any"]
    assert function_views["members/"]["methods"] == ["any"]
    assert function_views["public/"]["actions"] == {}


# DRF reads Django settings at import time, so the ViewSet is built in a child process with
# a fixture's settings loaded; `methods_for` is still called directly on the callable.
_VIEWSET_ACTIONS = """
import json, django
django.setup()
from rest_framework import viewsets
from authzlock.extract.methods import methods_for

class OrderViewSet(viewsets.ViewSet):
    def list(self, request):
        return None

    def destroy(self, request, pk=None):
        return None

methods, actions = methods_for(OrderViewSet.as_view({"get": "list", "delete": "destroy"}))
print(json.dumps({"methods": methods, "actions": list(actions.items())}))
"""


def test_t4_viewset_action_map() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _VIEWSET_ACTIONS],
        env=fixture_env("class_views"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["methods"] == ["DELETE", "GET"]
    assert data["actions"] == [["DELETE", "destroy"], ["GET", "list"]]


@pytest.mark.parametrize(
    "fixture",
    sorted(p.name for p in FIXTURES.iterdir() if (p / "urls.py").is_file()),
)
def test_t5_methods_sorted_uppercase_without_head_options(fixture: str) -> None:
    routes = run_extract(fixture)["routes"]
    assert routes
    for route in routes:
        methods = route["methods"]
        assert methods, route["path"]
        if methods == ["any"]:
            continue
        assert methods == sorted(methods)
        assert all(m == m.upper() for m in methods)
        assert not {"HEAD", "OPTIONS"} & set(methods)
        assert list(route["actions"]) == sorted(route["actions"])


def test_t6_http_method_names_restricts_handlers(class_views: dict[str, dict[str, Any]]) -> None:
    assert class_views["readonly/"]["methods"] == ["GET"]


def test_t7_wrapped_require_get_still_detected(
    function_views: dict[str, dict[str, Any]],
) -> None:
    def logged(view: Any) -> Any:
        @functools.wraps(view)
        def inner(request: HttpRequest) -> HttpResponse:
            response: HttpResponse = view(request)
            return response

        return inner

    @logged
    @require_GET
    def status(request: HttpRequest) -> HttpResponse:
        return HttpResponse("ok")

    assert methods_for(status) == (["GET"], {})
    assert function_views["status/"]["methods"] == ["GET"]

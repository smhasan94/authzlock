"""Tests for SHA-211: custom permission class registry."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest

from harness import fixture_env, run_extract

IS_OWNER = "api.permissions.IsOwner"


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return run_extract("drf_apiview")


def _route(data: dict[str, Any], path: str) -> dict[str, Any]:
    return next(route for route in data["routes"] if route["path"] == path)


def test_t1_custom_class_registered_with_docstring_and_used_by(data: dict[str, Any]) -> None:
    entry = data["custom_permissions"][IS_OWNER]
    assert entry["name"] == "IsOwner"
    assert entry["docstring"] == "Only the owner of an object may access it."
    assert "DELETE,GET orders/<int:pk>/ -> api.views.OrderDetailView" in entry["used_by"]


def test_t2_missing_docstring_is_null(data: dict[str, Any]) -> None:
    assert data["custom_permissions"]["api.permissions.NoDoc"]["docstring"] is None


def test_t3_builtins_are_not_registered(data: dict[str, Any]) -> None:
    assert data["custom_permissions"]
    assert not [name for name in data["custom_permissions"] if name.startswith("rest_framework.")]


def test_t4_composed_or_expression_rendered_and_registered(data: dict[str, Any]) -> None:
    route = _route(data, "composed/")
    expression = "(rest_framework.permissions.IsAuthenticated | api.permissions.IsOwner)"
    assert route["permission_classes"] == [expression]
    assert (
        "GET composed/ -> api.views.ComposedView" in data["custom_permissions"][IS_OWNER]["used_by"]
    )


def test_t5_exploding_class_never_executed(data: dict[str, Any]) -> None:
    entry = data["custom_permissions"]["api.permissions.Exploding"]
    assert entry["used_by"] == ["GET exploding/ -> api.views.ExplodingView"]


def test_t6_used_by_lists_three_sorted_keys(data: dict[str, Any]) -> None:
    used_by = data["custom_permissions"][IS_OWNER]["used_by"]
    assert used_by == sorted(used_by)
    assert used_by == [
        "DELETE,GET orders/<int:pk>/ -> api.views.OrderDetailView",
        "GET composed/ -> api.views.ComposedView",
        "GET notes/ -> api.views.NotesView",
    ]


# DRF reads Django settings at import time, so the holders are built in a child process.
_RENDER = """
import json, django
django.setup()
from rest_framework.permissions import IsAuthenticated
from api.permissions import IsBlocked, IsOwner
from authzlock.extract.custom import operand_classes, render_permission

negated = ~IsBlocked
both = (IsAuthenticated & IsOwner) | ~IsBlocked
print(json.dumps({
    "negated": render_permission(negated),
    "nested": render_permission(both),
    "operands": [c.__name__ for c in operand_classes(both)],
}))
"""


def test_t7_negation_expression(data: dict[str, Any]) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _RENDER],
        env=fixture_env("drf_apiview"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert rendered["negated"] == "(~api.permissions.IsBlocked)"
    assert rendered["nested"] == (
        "((rest_framework.permissions.IsAuthenticated & api.permissions.IsOwner)"
        " | (~api.permissions.IsBlocked))"
    )
    assert rendered["operands"] == ["IsAuthenticated", "IsOwner", "IsBlocked"]
    assert _route(data, "negated/")["permission_classes"] == ["(~api.permissions.IsBlocked)"]
    assert "api.permissions.IsBlocked" in data["custom_permissions"]
